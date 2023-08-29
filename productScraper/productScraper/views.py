import aiohttp
import asyncio
import re
import time
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup, SoupStrainer
from django.shortcuts import render
from django.http import HttpResponse


async def fetch_price(session, product_link):
    try:
        async with session.get(product_link) as response:
            html_content = await response.text()
            return html_content
    except Exception as e:
        print(f"Error fetching {product_link}: {e}")
        return None


async def fetch_sub_links(
    session, parent_href_formatted, product_name, sub_links, timeout=3
):
    try:
        async with session.get(parent_href_formatted, timeout=timeout) as response:
            content = await response.read()
            sub_soup = BeautifulSoup(
                content,
                "html.parser",
                parse_only=SoupStrainer("a", href=True),
                on_duplicate_attribute="replace",
            )
            sub_atags = sub_soup.find_all("a", href=True)
            for sub_atag in sub_atags:
                href_sub = sub_atag.get("href")
                sub_href = urljoin(parent_href_formatted, href_sub)
                sub_href = urlparse(sub_href).geturl()
                sub_links.append(sub_href)
                print(sub_href)
    except asyncio.TimeoutError:
        print(f"Timeout fetching sub links from {parent_href_formatted}")
    except Exception:
        pass


async def get_product_sub_links(session, soup, product_name, website_name):
    sub_links = {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 6.3; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.71 Safari/537.36"
    }

    getUrl = await get_url_formatting(product_name, website_name)

    get_parent_url = set(soup.find_all("a", href=True))

    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = [
            fetch_sub_links(
                session,
                urljoin(f"https://www.{website_name}.com.au", link.get("href")),
                product_name,
                sub_links.setdefault(urlparse(parent_href_formatted).geturl(), []),
            )
            for link in get_parent_url
        ]
        await asyncio.gather(*tasks)

    return sub_links


async def main(product_name, website_name):
    formatted_url = await get_url_formatting(product_name, website_name)
    print(f"Now searching for {product_name} in url {formatted_url}")

    start_time = time.time()

    async with aiohttp.ClientSession() as session:
        soup = await get_soup(formatted_url)

        if soup:
            product_data, count, sub_links_dict = await extract_product_info(
                soup, product_name, website_name, session
            )

            for product_info in product_data.values():
                print(f"Product Info:\n {product_info}\n")

            print(f"Total number of products found: {count}")

    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"Total time taken: {elapsed_time:.2f} seconds")
    return product_data


async def extract_product_info(soup, product_name, website_name, session):
    count = 0
    product_data = {}
    sub_links_dict = {}
    pattern = re.compile(re.escape(product_name), re.IGNORECASE)
    matched_elements = soup.find_all(string=pattern)

    tasks = [
        fetch_price(session, parent_element.get("href"))
        for element in matched_elements
        if (parent_element := element.find_parent()) is not None
        and (product_link := parent_element.get("href")) is not None
        and product_link.startswith(("http://", "https://"))
    ]
    html_contents = await asyncio.gather(*tasks)

    print("Number of html_contents:", len(html_contents))

    if len(html_contents) <= 10:
        sub_links_dict = await get_product_sub_links(soup, product_name, website_name)
        sub_links_tasks = [
            fetch_price(session, sub_link)
            for sub_link_list in sub_links_dict.values()
            for sub_link in sub_link_list
        ]
        sub_html_contents = await asyncio.gather(*sub_links_tasks)
        await process_matched_elements(
            matched_elements,
            html_contents,
            product_data,
        )
    else:
        await process_matched_elements(
            matched_elements, html_contents, product_data
        )

    return product_data, count, sub_links_dict


async def extract_product_price(html_content):
    price_pattern = r"\$\d+\.\d+|\£\d+|\d+\.\d+\s(?:USD|EUR)"
    prices = re.findall(price_pattern, html_content)
    return prices[0] if prices else "Price not found"


async def create_product_info(name, link, price, parent_element):
    return {
        "name": name,
        "link": link,
        "price": price,
        "parent_element": parent_element,
    }


async def process_matched_elements(matched_elements, html_contents, product_data):
    count = 0
    for i, element in enumerate(matched_elements):
        parent_element = element.find_parent()
        product_link = parent_element.get("href")

        if product_link is None or not product_link.startswith(("http://", "https://")):
            continue

        if i >= len(html_contents):
            continue

        product_price = await extract_product_price(html_contents[i])
        if not product_price:
            continue

        product_info = await create_product_info(
            element.strip(), product_link.strip(), product_price, parent_element
        )
        product_data[element.strip()] = product_info
        count += 1


async def get_soup(url_):
    html = await fetch_html(url_)
    if html:
        return BeautifulSoup(html, "lxml")
    else:
        print(f"Failed to fetch the webpage: {url_}")
        return None


async def fetch_html(url_):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 6.3; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.71 Safari/537.36"
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url_, headers=headers) as response:
            if response.status == 200:
                return await response.text()
            else:
                return None


async def get_url_formatting(product_name, website_name):
    product_end_formatted = product_name.replace(" ", "%20")
    product_formatted = product_name.replace(" ", "+")
    website_urls = {
        "rebelsport": f"https://www.rebelsport.com.au/search?q={product_end_formatted}",
        "harveynorman": f"https://www.harveynorman.com.au/search?q={product_formatted}",
        "ebay": f"https://www.ebay.com.au/sch/i.html?_from=R40&_trksid=p4432023.m570.l1313&_nkw={product_formatted}&_sacat=0",
        "thegoodguys": f"https://www.thegoodguys.com.au/SearchDisplay?categoryId=&storeId=900&catalogId=30000&langId=-1&sType=SimpleSearch&resultCatEntryType=2&showResultsPage=true&searchSource=Q&pageView=&beginIndex=0&orderBy=0&pageSize=30&searchTerm={product_formatted}",
        "kogan": f"https://www.kogan.com/au/shop/?q={product_formatted}",
        "officeworks": f"https://www.officeworks.com.au/shop/officeworks/search?q={product_end_formatted}&view=grid&page=1&sortBy=bestmatch",
        "jbhifi": f"https://www.jbhifi.com.au/search?page=1&query={product_end_formatted}&saleItems=false&toggle%5BonPromotion%5D=false",
        "ajeworld": f"https://ajeworld.com.au/collections/shop?q={product_formatted}",
        "myer": f"https://www.myer.com.au/search?query={product_formatted}",
    }
    if website_name not in website_urls:
        print("Unsupported website name:", website_name)
        return None

    url_formatted = website_urls[website_name]
    return url_formatted


async def search_view(request):
    if request.method == "POST":
        product_name = request.POST.get("product_name")
        website_name = request.POST.get("website_name")

        product_data = await main(product_name, website_name)

        return render(
            request,
            "productScraper/search_results.html",
            {"product_data": product_data},
        )

    return render(request, "productScraper/search_form.html")
