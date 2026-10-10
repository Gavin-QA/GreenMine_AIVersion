import os
import json
import requests
from pathlib import Path

ZENTAO_URL = "http://192.140.163.129:8080"
ACCOUNT = "guoxiaoqi"
PASSWORD = "yNSlLQs8ZBzlgOew"

def get_token():
    url = f"{ZENTAO_URL}/api.php/v1/tokens"
    resp = requests.post(url, json={"account": ACCOUNT, "password": PASSWORD})
    resp.raise_for_status()
    return resp.json()["token"]

def get_products(token):
    url = f"{ZENTAO_URL}/api.php/v1/products"
    resp = requests.get(url, headers={"Token": token})
    resp.raise_for_status()
    return resp.json().get("products", [])

def submit_bug(token, product_id, title, steps):
    url = f"{ZENTAO_URL}/api.php/v1/bugs"
    payload = {
        "product": product_id,
        "title": title,
        "steps": steps,
        # Default values required by Zentao
        "severity": 3,
        "pri": 3,
        "type": "codeerror",
        "os": "windows",
        "browser": "electron"
    }
    resp = requests.post(url, json=payload, headers={"Token": token})
    if resp.status_code not in (200, 201):
        raise Exception(f"提交禅道失败: {resp.text}")
    return resp.json()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-products", action="store_true", help="列出禅道里的所有产品")
    parser.add_argument("--submit-bug", type=str, help="从本地缺陷库里找到指定 ID 并提交到禅道")
    parser.add_argument("--product-id", type=int, help="禅道产品 ID", default=10) # 默认为某个 ID
    args = parser.parse_args()

    try:
        token = get_token()
        
        if args.list_products:
            products = get_products(token)
            print("可用产品列表:")
            for p in products:
                print(f"- ID: {p['id']}, Name: {p['name']}")
                
        elif args.submit_bug:
            bug_id = args.submit_bug
            bug_file = Path('artifacts/bugs/global_bugs.json')
            if not bug_file.exists():
                print("找不到全局缺陷库文件")
                exit(1)
                
            with open(bug_file, 'r', encoding='utf-8') as f:
                bugs = json.load(f)
                
            bug = next((b for b in bugs if b['id'] == bug_id), None)
            if not bug:
                print(f"在本地库中未找到 Bug: {bug_id}")
                exit(1)
                
            title = f"[{bug_id}] {bug['title']}"
            
            # Format steps
            steps_html = f"<p><strong>触发路径：</strong>{bug.get('ui_path', '无')}</p>"
            steps_html += f"<p><strong>最近报错：</strong><br/>{bug.get('actual', '')}</p>"
            
            print(f"正在提交 Bug 到禅道 (Product ID: {args.product_id}): {title}")
            res = submit_bug(token, args.product_id, title, steps_html)
            
            # Update local bug status
            bug['status'] = "已提单"
            bug['zentao_id'] = res.get('id')
            with open(bug_file, 'w', encoding='utf-8') as f:
                json.dump(bugs, f, ensure_ascii=False, indent=2)
                
            print(f"✅ 成功提交禅道，禅道内部 Bug ID: {res.get('id')}")
            
    except Exception as e:
        print(f"执行失败: {e}")
