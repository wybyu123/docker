import os
import csv
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

CSV_PATH = "20260826.csv"
TXT_DIR = "txt"
TIMEOUT = 2.5

def log(msg):
    """带时间戳的日志输出函数，方便直观查看运行节奏"""
    current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    print(f"[{current_time}] {msg}")

def get_ips_from_csv(csv_path):
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
    url = f"http://{ip}:85/iptv_ad01.jpg"
    try:
        response = requests.get(url, timeout=TIMEOUT)
        if response.status_code == 200:
            return ip
    except Exception:
        pass
    return None

def extract_template_paths():
    log("正在从已有 txt 模板中提取频道路径结构...")
    templates = set()
    if not os.path.exists(TXT_DIR):
        log(f"⚠️ 提示：本地未发现 {TXT_DIR} 目录，将使用默认路径规则兜底。")
        return list(templates)
        
    for filename in os.listdir(TXT_DIR):
        if filename.endswith(".txt"):
            file_path = os.path.join(TXT_DIR, filename)
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if "http://" in line and ".m3u8" in line:
                        parts = line.strip().split(",")
                        if len(parts) >= 2:
                            url = parts[1].strip()
                            if ":85" in url:
                                path = url.split(":85")[1]
                                templates.add(path)
    log(f"✅ 提取完毕，共获得 {len(templates)} 条唯一的频道路径模板。")
    return list(templates)

def test_and_save_sources(live_ips, templates):
    if not live_ips or not templates:
        log("⚠️ 存活 IP 或模板为空，终止爆破探测阶段。")
        return

    os.makedirs(TXT_DIR, exist_ok=True)
    total_found_sources = 0

    log(f"开始对 {len(live_ips)} 个存活 IP 进行全量模板爆破探测...")
    for idx, ip in enumerate(live_ips, 1):
        log(fn=f"--- [{idx}/{len(live_ips)}] 正在检测 IP: {ip} ---")
        valid_channels = []
        
        for template_path in templates:
            test_url = f"http://{ip}:85{template_path}"
            try:
                res = requests.head(test_url, timeout=TIMEOUT)
                if res.status_code != 200:
                    res = requests.get(test_url, timeout=TIMEOUT)
                
                if res.status_code == 200:
                    valid_channels.append(test_url)
            except Exception:
                pass
        
        if valid_channels:
            log(f"🎉 【命中】IP {ip} 发现有效频道：{len(valid_channels)} 个！")
            total_found_sources += len(valid_channels)
            output_file = os.path.join(TXT_DIR, f"{ip}-85.txt")
            
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(f"自动扫描新源_{ip},#genre#\n")
                for c_idx, url in enumerate(valid_channels, 1):
                    f.write(f"频道_{c_idx},{url}\n")
            log(fn=f"💾 已成功写入文件: {output_file}")
        else:
            log(f"em... IP {ip} 未扫描到可用频道。")

    log(f"✨ 探测结束！本次共挖掘并保存了 {total_found_sources} 个有效直播源。")

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
                print(f"  [√] 发现存活目标 --> {res_ip}")
                live_ips.append(res_ip)

    log(f"👉 阶段 1 完成：在 {len(ips)} 个 IP 中，共筛选出 {len(live_ips)} 个存活主机。")

    log("[阶段 2/3] 正在加载已有频道模板...")
    templates = extract_template_paths()

    log("[阶段 3/3] 开始对存活 IP 逐个进行频道匹配与校验...")
    test_and_save_sources(live_ips, templates)
    
    log("=== 全部任务圆满完成！ ===")

if __name__ == "__main__":
    main()
