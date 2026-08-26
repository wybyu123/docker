import os
import csv
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# 配置路径
CSV_PATH = "20260826.csv"
TXT_DIR = "txt"

# 超时设置
TIMEOUT = 2.5

def get_ips_from_csv(csv_path):
    """从 FOFA 的 CSV 文件中提取 IP 地址"""
    ips = set()
    if not os.path.exists(csv_path):
        print(f"[-] 未找到 CSV 文件: {csv_path}")
        return list(ips)
    
    with open(csv_path, mode="r", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 兼容不同表头名称，优先取 ip 或 host
            ip = row.get("ip") or row.get("host", "").split(":")[0]
            if ip:
                ips.add(ip.strip())
    print(f"[+] 从 CSV 共提取到 {len(ips)} 个唯一 IP。")
    return list(ips)

def check_ip_alive(ip):
    """测试 IP 的 85 端口是否存活（请求根目录或首页广告图片）"""
    url = f"http://{ip}:85/iptv_ad01.jpg"
    try:
        response = requests.get(url, timeout=TIMEOUT)
        if response.status_code == 200:
            return ip
    except Exception:
        pass
    return None

def extract_template_paths():
    """
    从现有 txt 模板中提取频道的路径规律。
    例如把 http://114.245.198.169:85/tsfile/live/1/1001_1.m3u8?key=txiptv 
    转化为模板格式: /tsfile/live/{type}/{chid}_1.m3u8?key=txiptv 
    或者直接提取具体的 path 组合 (type, chid)
    """
    templates = set()
    if not os.path.exists(TXT_DIR):
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
                            # 提取域名之后的内容，例如 /tsfile/live/1/1001_1.m3u8?key=txiptv
                            if ":85" in url:
                                path = url.split(":85")[1]
                                templates.add(path)
    print(f"[+] 从现有模板中共提取到 {len(templates)} 条频道路径特征模板。")
    return list(templates)

def test_and_save_sources(live_ips, templates):
    """对存活的 IP 结合模板进行批量频道探测"""
    if not live_ips or not templates:
        print("[-] 没有存活的 IP 或没有可用模板，跳过探测。")
        return

    os.makedirs(TXT_DIR, exist_ok=True)

    for ip in live_ips:
        print(f"[*] 正在检测新 IP: {ip}")
        valid_channels = []
        
        # 针对每个存活 IP，测试所有模板路径
        for template_path in templates:
            # 替换模板中的特定数字或直接利用原路径拼接
            test_url = f"http://{ip}:85{template_path}"
            try:
                # 用 HEAD 或 GET 快速检测状态码
                res = requests.head(test_url, timeout=TIMEOUT)
                if res.status_code != 200:
                    res = requests.get(test_url, timeout=TIMEOUT)
                
                if res.status_code == 200:
                    # 尝试从原模板中反推频道名称（这里简化：如果请求成功，保留其后缀路径并组装）
                    valid_channels.append(test_url)
            except Exception:
                pass
        
        if valid_channels:
            print(f"[+] IP {ip} 发现有效频道 {len(valid_channels)} 个！写入文件。")
            output_file = os.path.join(TXT_DIR, f"{ip}-85.txt")
            
            # 按照原有的 #genre# 格式写入新文件
            with open(output_file, "w", encoding="utf-8") as f:
                f.write("自动扫描新源,#genre#\n")
                for idx, url in enumerate(valid_channels, 1):
                    f.write(f"频道_{idx},{url}\n")

def main():
    ips = get_ips_from_csv(CSV_PATH)
    if not ips:
        return

    print("[*] 开始第一步：多线程筛选 85 端口存活的 IP...")
    live_ips = []
    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(check_ip_alive, ip): ip for ip in ips}
        for future in as_completed(futures):
            res_ip = future.result()
            if res_ip:
                print(f"  [√] 存活: {res_ip}")
                live_ips.append(res_ip)

    print(f"[+] 存活 IP 筛选完毕，共计 {len(live_ips)} 个有效目标。")

    print("[*] 开始第二步：提取现有模板路径...")
    templates = extract_template_paths()

    print("[*] 开始第三步：对存活 IP 进行频道有效性爆破与新源生成...")
    test_and_save_sources(live_ips, templates)
    print("[✔] 全部任务执行完毕！")

if __name__ == "__main__":
    main()
