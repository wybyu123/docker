import os
import csv
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# 配置路径
CSV_PATH = "20260826.csv"
TXT_DIR = "txt"

# 超时设置（秒）
TIMEOUT = 2.0
INNER_WORKERS = 30

def log(msg):
    """带时间戳的日志输出函数，并强制开启 flush=True 实现实时打印"""
    current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    print(f"[{current_time}] {msg}", flush=True)

def get_ips_from_csv(csv_path):
    """从 CSV 文件中提取 IP 地址"""
    log(f"正在读取 CSV 文件: {csv_path}")
    ips = set()
    if not os.path.exists(csv_path):
        log(f"❌ 错误：未找到文件 {csv_path}")
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

def load_templates():
    """
    从现有 txt 模板中完整加载分类、频道名及对应的相对路径结构。
    返回结构示例: 
    [
        {"category": "央视", "name": "CCTV1", "path": "/tsfile/live/33/1007.m3u8?key=txiptv"},
        ...
    ]
    """
    log("正在从已有 txt 模板中提取分类、频道名与路径结构...")
    templates = []
    seen = set()
    
    if not os.path.exists(TXT_DIR):
        log(f"⚠️ 提示：本地未发现 {TXT_DIR} 目录。")
        return templates
        
    for filename in os.listdir(TXT_DIR):
        if filename.endswith(".txt"):
            file_path = os.path.join(TXT_DIR, filename)
            current_category = "其他"
            
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    # 识别分类标签，如 央视,#genre# 或 卫视,#genre#
                    if "#genre#" in line:
                        current_category = line.split(",")[0].strip()
                        continue
                    
                    # 识别频道行，如 CCTV1,http://...
                    if "," in line and "http://" in line:
                        parts = line.split(",", 1)
                        name = parts[0].strip()
                        url = parts[1].strip()
                        
                        if ":85" in url:
                            # 提取 :85 后面的路径部分（包含参数）
                            path = url.split(":85", 1)[1]
                            unique_key = (current_category, name, path)
                            if unique_key not in seen:
                                seen.add(unique_key)
                                templates.append({
                                    "category": current_category,
                                    "name": name,
                                    "path": path
                                })
                                
    log(f"✅ 模板加载完毕，共提取到 {len(templates)} 个带名字和分类的有效频道模板。")
    return templates

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

def test_and_save_sources(live_ips, templates):
    """对存活的 IP 进行多线程频道验证，并严格按原模板分类与命名写出文件"""
    if not live_ips or not templates:
        log("⚠️ 存活 IP 或模板为空，终止探测阶段。")
        return

    os.makedirs(TXT_DIR, exist_ok=True)
    total_found_sources = 0

    log(f"开始对 {len(live_ips)} 个存活 IP 进行多线程模板爆破探测...")
    for idx, ip in enumerate(live_ips, 1):
        log(f"--- [{idx}/{len(live_ips)}] 正在检测 IP: {ip} ---")
        valid_channels = []
        
        # 多线程并发测试当前 IP 的所有频道模板
        with ThreadPoolExecutor(max_workers=INNER_WORKERS) as executor:
            futures = {executor.submit(test_single_channel, ip, item): item for item in templates}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    valid_channels.append(result)
        
        if valid_channels:
            log(f"🎉 【命中】IP {ip} 发现有效频道：{len(valid_channels)} 个！")
            total_found_sources += len(valid_channels)
            output_file = os.path.join(TXT_DIR, f"{ip}-85.txt")
            
            # 按分类归类整理
            categories = {}
            for ch in valid_channels:
                cat = ch["category"]
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append((ch["name"], ch["url"]))
            
            # 写入文件，严格保持分类和频道名字
            with open(output_file, "w", encoding="utf-8") as f:
                for cat, ch_list in categories.items():
                    f.write(f"{cat},#genre#\n")
                    for name, url in ch_list:
                        f.write(f"{name},{url}\n")
            
            log(f"💾 已成功写入排版文件: {output_file}")
        else:
            log(f"em... IP {ip} 未扫描到可用频道。")

    log(f"✨ 探测结束！本次共挖掘并保存了 {total_found_sources} 个有效直播源文件。")

def main():
    log("=== IPTV 自动探测与新源挖掘脚本开始运行 ===")
    
    ips = get_ips_from_csv(CSV_PATH)
    if not ips:
        return

    log("[阶段 1/3] 开始多线程探测 85 端口存活状态...")
    live_ips = []
    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(check_ip_alive, ip): ip for ip in ips}
        for future in as_completed(futures):
            res_ip = future.result()
            if res_ip:
                print(f"  [√] 发现存活目标 --> {res_ip}", flush=True)
                live_ips.append(res_ip)

    log(f"👉 阶段 1 完成：在 {len(ips)} 个 IP 中，共筛选出 {len(live_ips)} 个存活主机。")

    log("[阶段 2/3] 正在加载已有频道模板...")
    templates = load_templates()

    log("[阶段 3/3] 开始对存活 IP 逐个进行多线程频道匹配与校验...")
    test_and_save_sources(live_ips, templates)
    
    log("=== 全部任务圆满完成！ ===")

if __name__ == "__main__":
    main()
