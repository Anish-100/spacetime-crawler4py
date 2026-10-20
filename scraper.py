import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup

UNIQUE_DOMAINS_FILE = './files/unique_domains.txt'
VISITED_PAGES_FILE = './files/pages_visited.txt'

def load_set(path):
    try:
        with open(path) as f:
            return {line.strip() for line in f if line.strip()}
    except FileNotFoundError:
        return set()

unique_domains = load_set(UNIQUE_DOMAINS_FILE)
visited_pages = load_set(VISITED_PAGES_FILE)

def write_line_to_file(file_name, text):
    """
    This is a helper function that takes in some text then writes the text
    to the given file_name with a new line at the end
    """
    with open(file_name, 'a') as f:
        f.write(f'{text}\n')
        f.write('\n')

def _add_to_unique(url):
    """
    Adds the url to the list of unique domains if it hasn't been listed yet
    """
    parsed = urlparse(url)
    new_url = parsed.netloc
    if  new_url not in unique_domains:
        unique_domains.add(new_url)
        write_line_to_file('./files/unique_domains.txt', f'{new_url}')

def _is_unvisited(url):
    """
    Checked if the url is in the set of visited pages.
    Returns false if the page is has not been visited otherwise
    returns true and adds it to the visited pages
    """
    if url in visited_pages:
        return False
    visited_pages.add(url)
    return True

def scraper(url, resp):
    res = []
    if _is_valid(url):
        _add_to_unique(url)
        _is_unvisited(url)
        links = extract_next_links(url, resp)

        for link in links:
            if _is_valid(link) and not _is_unvisited(link):
                _add_to_unique(link)
                res.append(link)

    return res

def extract_next_links(url, resp):
    # Implementation required.
    # url: the URL that was used to get the page
    # resp.url: the actual url of the page
    # resp.status: the status code returned by the server. 200 is OK, you got the page. Other numbers mean that there was some kind of problem.
    # resp.error: when status is not 200, you can check the error here, if needed.
    # resp.raw_response: this is where the page actually is. More specifically, the raw_response has two parts:
    #         resp.raw_response.url: the url, again
    #         resp.raw_response.content: the content of the page!
    # Return a list with the hyperlinks (as strings) scrapped from resp.raw_response.content
    res = []
    if resp.error is not None:
        write_line_to_file('./files/failed_pages.txt', f'{resp.url} raised Error {resp.error}.')
        return []
    soup = BeautifulSoup(resp.raw_response.content, "html.parser")
    for anchor in soup.find_all('a'):
       res.append(anchor.get("href",'/'))
    return res

def _is_valid(url):
    # Decide whether to crawl this url or not. 
    # If you decide to crawl it, return True; otherwise return False.
    # There are already some conditions that return False.
    allowed_sites = [
        re.compile(r"^([a-z0-9-]+\.)*ics.uci.edu$"),
        re.compile(r"^([a-z0-9-]+\.)*cs.uci.edu$"),
        re.compile(r"^([a-z0-9-]+\.)*informatics.uci.edu$"),
        re.compile(r"^([a-z0-9-]+\.)*stat.uci.edu$"),
    ]
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        
        return any(site.match(parsed.netloc) for site in allowed_sites) and not re.match(
            r".*\.(css|js|bmp|gif|jpe?g|ico"
            + r"|png|tiff?|mid|mp2|mp3|mp4"
            + r"|wav|avi|mov|mpeg|ram|m4v|mkv|ogg|ogv|pdf"
            + r"|ps|eps|tex|ppt|pptx|doc|docx|xls|xlsx|names"
            + r"|data|dat|exe|bz2|tar|msi|bin|7z|psd|dmg|iso"
            + r"|epub|dll|cnf|tgz|sha1"
            + r"|thmx|mso|arff|rtf|jar|csv"
            + r"|rm|smil|wmv|swf|wma|zip|rar|gz)$", parsed.path.lower()
        )
    except Exception as e:
        write_line_to_file('./files/failed_pages.txt',f'Invalid URL: {url}, Type: {e}')