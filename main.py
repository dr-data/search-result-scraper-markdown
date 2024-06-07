import os
from dotenv import load_dotenv
import httpx
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from markdownify import markdownify as md
from bs4 import BeautifulSoup, Comment
import json

# Load .env file
load_dotenv()

# Retrieve environment variables
SEARXNG_URL = os.getenv('SEARXNG_URL')
BROWSERLESS_URL = os.getenv('BROWSERLESS_URL')
TOKEN = os.getenv('TOKEN')
PROXY_PROTOCOL = os.getenv('PROXY_PROTOCOL', 'http')
PROXY_URL = os.getenv('PROXY_URL')
PROXY_USERNAME = os.getenv('PROXY_USERNAME')
PROXY_PASSWORD = os.getenv('PROXY_PASSWORD')
PROXY_PORT = os.getenv('PROXY_PORT')
REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '30'))

# Domains that should only be accessed using Browserless
domains_only_for_browserless = ["twitter", "x", "facebook"] # Add more domains here

# Create FastAPI app
app = FastAPI()

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def fetch_normal_content(url, proxies):
    try:
        response = httpx.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, proxies=proxies)
        response.raise_for_status()
        return response.text
    except httpx.RequestError as e:
        print(f"An error occurred while requesting {url}: {e}")
    except httpx.HTTPStatusError as e:
        print(f"HTTP error occurred: {e}")
    return None

def fetch_browserless_content(url, proxies):
    try:
        browserless_url = f"{BROWSERLESS_URL}/content"
        
        params = {}
        if TOKEN:
            params['token'] = TOKEN
            
        proxy_url = f"{PROXY_PROTOCOL}://{PROXY_URL}:{PROXY_PORT}" if PROXY_URL and PROXY_PORT else None
        if proxy_url:
            params['--proxy-server'] = proxy_url
            
        browserless_data = {
            "url": url,
            "rejectResourceTypes": ["image"],
            "rejectRequestPattern": ["/^.*\\.(css)/"],
            "gotoOptions": {"waitUntil": "networkidle2"},
            "bestAttempt": True
        }
        if PROXY_USERNAME and PROXY_PASSWORD:
            browserless_data["authenticate"] = {
                "username": PROXY_USERNAME,
                "password": PROXY_PASSWORD
            }
            
        headers = {
            'Cache-Control': 'no-cache',
            'Content-Type': 'application/json'
        }
        
        response = httpx.post(browserless_url, params=params, headers=headers, data=json.dumps(browserless_data), timeout=REQUEST_TIMEOUT*2)

        response.raise_for_status()
        return response.text
    except httpx.RequestError as e:
        print(f"An error occurred while requesting Browserless for {url}: {e}")
    except httpx.HTTPStatusError as e:
        print(f"HTTP error occurred with Browserless: {e}")
    return None

def fetch_content(url):
    proxies = None
    if PROXY_URL and PROXY_USERNAME and PROXY_PORT:
        proxies = {
            "http://": f"{PROXY_PROTOCOL}://{PROXY_USERNAME}:{PROXY_PASSWORD}@{PROXY_URL}:{PROXY_PORT}",
            "https://": f"{PROXY_PROTOCOL}://{PROXY_USERNAME}:{PROXY_PASSWORD}@{PROXY_URL}:{PROXY_PORT}"
        }
        print(f"Using proxy {proxies}")
    if any(domain in url for domain in domains_only_for_browserless):
        content = fetch_browserless_content(url, proxies)
    else:
        content = fetch_normal_content(url, proxies)
        if content is None:
            content = fetch_browserless_content(url, proxies)

    return content

def clean_html(html):
    soup = BeautifulSoup(html, 'html.parser')
    
    # Remove all script, style, and other unnecessary elements
    for script_or_style in soup(["script", "style", "header", "footer", "noscript", "form", "input", "textarea", "select", "option", "button", "svg", "iframe", "object", "embed", "applet"]):
        script_or_style.decompose()
    
    # Remove unwanted classes and ids
    for tag in soup.find_all(True):
        tag.attrs = {key: value for key, value in tag.attrs.items() if key not in ['class', 'id', 'style']}
    
    # Remove comments
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    
    return str(soup)

def parse_html_to_markdown(html, url):
    cleaned_html = clean_html(html)
    markdown_content = md(cleaned_html)
    return {
        "title": BeautifulSoup(html, 'html.parser').title.string if BeautifulSoup(html, 'html.parser').title else 'No title',
        "url": url,
        "md": clean_markdown(markdown_content)
    }

def clean_markdown(markdown):
    # Remove extra newlines and whitespace
    lines = markdown.split('\n')
    cleaned_lines = [line.strip() for line in lines if line.strip()]
    return '\n'.join(cleaned_lines)

def search(query: str, num_results: int) -> list:
    searxng_query_url = f"{SEARXNG_URL}/search?q={query}&categories=general&format=json"
    try:
        response = httpx.get(searxng_query_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except httpx.RequestError as e:
        return [{"error": f"Search query failed with error: {e}"}]
    except httpx.HTTPStatusError as e:
        return [{"error": f"Search query failed with HTTP error: {e}"}]

    search_results = response.json()
    results = []
    
    for result in search_results["results"][:num_results]:
        url = result["url"]
        title = result["title"]
        html_content = fetch_content(url)
        if html_content:
            markdown_data = parse_html_to_markdown(html_content, url)
            results.append({
                "title": title,
                "url": url,
                "markdown_content": (
                f"Title: {markdown_data['title']}\n\n"
                f"URL Source: {markdown_data['url']}\n\n"
                f"Markdown Content:\n{markdown_data['md']}"
            )
            })
    
    return results

@app.get("/", response_class=JSONResponse)
def get_search_results(q: str = Query(..., description="Search query"), num_results: int = Query(5, description="Number of results")):
    result_list = search(q, num_results)
    return result_list

@app.get("/r/{url:path}", response_class=PlainTextResponse)
def fetch_url(url: str):
    html_content = fetch_content(url)
    if html_content:
        markdown_data = parse_html_to_markdown(html_content, url)
        response_text = (
            f"Title: {markdown_data['title']}\n\n"
            f"URL Source: {markdown_data['url']}\n\n"
            f"Markdown Content:\n{markdown_data['md']}"
        )
        return PlainTextResponse(response_text)
    return PlainTextResponse("Failed to retrieve content")

# Example usage
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
