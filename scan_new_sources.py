import os
import csv
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================= 本地运行配置项 =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CSV_PATH = os.path.join(BASE_DIR, "20260826.csv")
TXT_DIR = os.path.join(BASE_DIR, "txt")
M3U_OUTPUT_DIR = os.path.join(BASE_DIR, "m3u_output")

# 超时设置（秒）
TIMEOUT = 2.0
INNER_WORKERS = 30
ALIVE_WORKERS = 30

# 💡 核心优化：将固定值改为动态百分比阈值（例如 0.6 代表必须达到该模板总频道数的 60% 才算匹配）
MATCH_PERCENT_THRESHOLD = 0.60
# ====================================================

def log(msg):
    """带时间戳的本地日志输出函数"""
    current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    print(f"[{current_time}] {msg}", flush=True)

def get_ips_from_csv(csv_path):
    """从本地 CSV 文件中提取 IP 地址"""
    log(f"正在读取 CSV 文件: {csv_path}")
    ips = set()
    if not os.path.exists(csv_path):
        log(f"❌ 错误：未在本地找到文件 {csv_path}")
        return list(ips)
    
    with open(csv_path, mode="r", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ip = row.get("ip") or row.get("host", "").split(":")[0]
            if ip:
                ips.add(ip.strip())
    log(f"✅ 成功解析，去重后共获取到 {len(ips)} 个目标 IP。")
    return list(ips)

def check_ip_alive(ip):
    """测试 IP 的 85 端口是否存活"""
    url = f"http://{ip}:85/iptv_ad01.jpg"
    try:
        response = requests.get(url, timeout=TIMEOUT)
        if response.status_code == 200:
            return ip
    except Exception:
        pass
    return None

def load_txt_templates():
    """以【单个 txt 文件】为单位加载模板，并保留完整的分类与顺序。"""
    log(f"正在从本地 {TXT_DIR} 目录按文件加载模板...")
    templates_dict = {}
    
    if not os.path.exists(TXT_DIR):
        log(f"⚠️ 提示：未发现 {TXT_DIR} 目录。")
        return templates_dict
        
    for filename in os.listdir(TXT_DIR):
        if filename.endswith(".txt"):
            file_path = os.path.join(TXT_DIR, filename)
            template_name = os.path.splitext(filename)[0]
            
            channels = []
            current_category = "其他"
            
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    if "#genre#" in line:
                        current_category = line.split(",")[0].strip()
                        continue
                    
                    if "," in line and "http://" in line:
                        parts = line.split(",", 1)
                        name = parts[0].strip()
                        url = parts[1].strip()
                        
                        if ":85" in url:
                            path = url.split(":85", 1)[1]
                            channels.append({
                                "category": current_category,
                                "name": name,
                                "path": path
                            })
            
            if channels:
                templates_dict[template_name] = channels
                log(f"  - 加载模板文件 [{filename}]: 包含 {len(channels)} 个有效频道")
                
    log(f"✅ 模板加载完毕，共加载了 {len(templates_dict)} 个独立的 txt 模板文件。")
    return templates_dict

def test_single_channel(ip, item):
    """测试单个频道链接是否可用"""
    test_url = f"http://{ip}:85{item['path']}"
    try:
        res = requests.head(test_url, timeout=TIMEOUT)
        if res.status_code != 200:
            res = requests.get(test_url, timeout=TIMEOUT)
        
        if res.status_code == 200:
            return {
                "category": item["category"],
                "name": item["name"],
                "url": test_url
            }
    except Exception:
        pass
    return None

def process_ip_with_templates(ip, templates_dict):
    """
    针对单个 IP，测试各个 txt 模板。
    只有当有效频道数占该模板总频道数的比例 >= 60% 时，才判定匹配并完整生成 M3U 文件。
    """
    os.makedirs(M3U_OUTPUT_DIR, exist_ok=True)
    generated_count = 0

    for tpl_name, channels in templates_dict.items():
        total_template_count = len(channels)
        if total_template_count == 0:
            continue
            
        # 计算该模板要求的最低达标频道数（总数的 60%）
        required_threshold = int(total_template_count * MATCH_PERCENT_THRESHOLD)
        if required_threshold < 1:
            required_threshold = 1

        log(f"  👉 正在用模板 [{tpl_name}.txt] 测试 IP: {ip} (总数: {total_template_count}, 及格线: >= {required_threshold}个)...")
        
        valid_channels = []
        
        # 并发测试当前模板内的所有频道
        with ThreadPoolExecutor(max_workers=INNER_WORKERS) as executor:
            futures = {executor.submit(test_single_channel, ip, item): item for item in channels}
            
            for future in as_completed(futures):
                result = future.result()
                if result:
                    valid_channels.append(result)

        valid_count = len(valid_channels)
        ratio = valid_count / total_template_count

        # 💡 核心判定：有效播放数必须达到该模板总数的 60% 以上
        if valid_count >= required_threshold:
            log(f"    🎉 [匹配成功] IP {ip} 在模板 [{tpl_name}] 中有效频道 {valid_count}/{total_template_count} (占比 {ratio*100:.1f}%)，达到 >= {int(MATCH_PERCENT_THRESHOLD*100)}% 门槛！")
            
            # 直接完整保留该模板的有效频道并写入文件
            output_filename = f"{ip}_{tpl_name}.m3u"
            output_file = os.path.join(M3U_OUTPUT_DIR, output_filename)
            
            with open(output_file, "w", encoding="utf-8") as f:
                f.write("#EXTM3U\n")
                for ch in valid_channels:
                    f.write(f'#EXTINF:-1 tvg-name="{ch["name"]}" group-title="{ch["category"]}",{ch["name"]}\n')
                    f.write(f"{ch['url']}\n")
            
            log(f"    💾 [保存成功] 已生成高精度 M3U -> {output_filename}")
            generated_count += 1
        else:
            log(f"    ⏩ 模板 [{tpl_name}] 有效频道仅 {valid_count} 个（未达到总数 60% 的及格线），判定为不匹配，跳过。")
            
    return generated_count

def main():
    log("=== IPTV 按独立 txt 模板动态百分比匹配脚本开始运行 ===")
    
    ips = get_ips_from_csv(CSV_PATH)
    if not ips:
        return

    log("[阶段 1/3] 开始多线程探测 85 端口存活状态...")
    live_ips = []
    with ThreadPoolExecutor(max_workers=ALIVE_WORKERS) as executor:
        futures = {executor.submit(check_ip_alive, ip): ip for ip in ips}
        for future in as_completed(futures):
            res_ip = future.result()
            if res_ip:
                print(f"  [√] 发现存活目标 --> {res_ip}", flush=True)
                live_ips.append(res_ip)

    log(f"👉 阶段 1 完成：在 {len(ips)} 个 IP 中，共筛选出 {len(live_ips)} 个存活主机。")

    log("[阶段 2/3] 正在加载独立的 txt 模板文件...")
    templates_dict = load_txt_templates()
    if not templates_dict:
        log("❌ 错误：没有加载到任何有效的 txt 模板文件，程序退出。")
        return

    log("[阶段 3/3] 开始对每个存活 IP 逐个应用模板进行 60% 比例门槛测试与精准 M3U 生成...")
    total_files = 0
    for idx, ip in enumerate(live_ips, 1):
        log(f"\n--- [{idx}/{len(live_ips)}] 正在检测 IP: {ip} ---")
        count = process_ip_with_templates(ip, templates_dict)
        total_files += count

    log(f"\n=== 全部任务圆满完成！共精准生成了 {total_files} 个高质量 M3U 文件到目录: {M3U_OUTPUT_DIR} ===")

if __name__ == "__main__":
    main()
