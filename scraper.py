import os
import re
import json
import hashlib
from collections import Counter
from urllib.parse import urlparse, urljoin, urldefrag
from bs4 import BeautifulSoup

os.makedirs('./files', exist_ok=True)
VISITED_PAGES_FILE = './files/pages_visited.txt'   # one URL per line (for unique pages + subdomains)
STATS_FILE = './files/stats.json'                  # word counts + longest page
FAILED_FILE = './files/failed_pages.txt'
HASH_FILE = './files/page_hashes.txt'

MAX_BYTES = 5 * 1024 * 1024    # skip files over 5 MB
MIN_WORDS = 50                 # pages with fewer words = low information
MAX_URL_LEN = 200              # very long URLs are usually traps
NUM_HASH_BITS = 64             # hashes for simhash are 64 bits

ALLOWED_SITES = ["ics.uci.edu", "cs.uci.edu", "informatics.uci.edu", "stat.uci.edu"]

# calendars, date archives, and action links tend to be infinite traps
TRAP_REGEX = re.compile(
    r"(calendar|ical|\d{4}-\d{2}-\d{2}|\d{4}/\d{2}/\d{2}|action=|do=|share=|replytocom|"
    r"login|logout|sessionid|/feed|/wp-json|\?.*(sort|filter|format)=)", re.I)

STOP_WORDS = set("""a about above after again against all am an and any are aren't as at be because been before being below between both but by can't cannot could couldn't did didn't do does doesn't doing don't down during each few for from further had hadn't has hasn't have haven't having he he'd he'll he's her here here's hers herself him himself his how how's i i'd i'll i'm i've if in into is isn't it it's its itself let's me more most mustn't my myself no nor not of off on once only or other ought our ours ourselves out over own same shan't she she'd she'll she's should shouldn't so some such than that that's the their theirs them themselves then there there's these they they'd they'll they're they've this those through to too under until up very was wasn't we we'd we'll we're we've were weren't what what's when when's where where's which while who who's whom why why's with won't would wouldn't you you'd you'll you're you've your yours yourself yourselves""".split())

# ---- load saved state so a restart doesn't lose data ----
def load_stats():
    '''
    Loads the stats from previous sessions.
    '''
    try:
        with open(STATS_FILE) as f:
            d = json.load(f)
        return Counter(d["words"]), d["longest"]
    except (FileNotFoundError, ValueError):
        return Counter(), ["", 0]   # [url, word count]

def load_hashes():
    '''
    Loads all the hashes of previous pages
    '''
    try:
        with open(HASH_FILE) as f:
            return [int(line) for line in f if line.strip()]
    except FileNotFoundError:
        return []     # if this is the first time running and page_hashes.txt doesn't exist, it'll be created

    
        

word_counts, longest_page = load_stats()
pages_since_save = 0
page_hashes = load_hashes()

def save_stats():
    '''
    Saves stats for the report.
    '''
    with open(STATS_FILE, 'w') as f:
        json.dump({"words": word_counts, "longest": longest_page}, f)

def write_line_to_file(file_name, text):
    '''
    Appends a line of text to a file.
    '''
    with open(file_name, 'a') as f:
        f.write(f'{text}\n')

def scraper(url, resp):
    '''
    Returns next links from a page given they are valid.
    '''
    links = extract_next_links(url, resp)
    return [link for link in links if _is_valid(link)]

def extract_next_links(url, resp):
    '''
    Returns a list of the links from a given page and updates the report.
    '''
    global pages_since_save

    # only process good responses that actually contain a page
    if resp.status != 200 or resp.raw_response is None or not resp.raw_response.content or resp.error is not None:
        write_line_to_file(FAILED_FILE, f'{url} status={resp.status} error={resp.error}')
        return []

    content = resp.raw_response.content
    if len(content) > MAX_BYTES:       # very large file
        return []

    # use the final URL (after redirects) as the base for relative links
    base_url = urldefrag(resp.raw_response.url or url)[0]

    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script", "style"]):      # code/markup are not words
        tag.decompose()
    words = re.findall(r"[a-z0-9]+(?:'[a-z]+)?", soup.get_text(separator=" ").lower())

    # record this page as a unique page found (for the report)
    write_line_to_file(VISITED_PAGES_FILE, base_url)

    # low-information / dead page: don't count its words or follow its links
    if len(words) < MIN_WORDS:
        return []

    content_words = [w for w in words if w not in STOP_WORDS and len(w) > 1]


    # duplicate page: don't count its words or follow its links
    page_hash = _get_simhash(content_words)
    if _is_simhash_match(page_hash):
       return []
    
    # update stats for the report
    if len(words) > longest_page[1]:
                longest_page[0], longest_page[1] = base_url, len(words)
    word_counts.update(content_words) # content_words as stop words are removed.
    pages_since_save += 1
    if pages_since_save >= 10:
        save_stats()
        pages_since_save = 0

    # collect links: make absolute, remove fragment
    res = []
    for anchor in soup.find_all('a', href=True):
        try:
            link = urldefrag(urljoin(base_url, anchor['href'].strip()))[0]
        except ValueError:      # malformed href (e.g. bad IPv6 bracket host)
            continue
        res.append(link)
    return res

def _is_valid(url):
    '''
    Returns true if a URL is valid.

    Checks url length, http/https, domain, common traps, and non-text file types. 
    '''
    try:
        if not url.isascii() or len(url) > MAX_URL_LEN:
            return False
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False

        # must be one of the 4 allowed domains (or a subdomain of them)
        host = (parsed.hostname or "").lower()
        if not any(host == d or host.endswith("." + d) for d in ALLOWED_SITES):
            return False

        # trap: calendars, action links, etc.
        if TRAP_REGEX.search(parsed.path + "?" + parsed.query):
            return False

        # trap: a path segment repeating 3+ times (e.g. /a/b/a/b/a/b)
        segments = [s for s in parsed.path.split("/") if s]
        if segments and max(Counter(segments).values()) >= 3:
            return False

        # skip non-text file types
        return not re.match(
            r".*\.(css|js|bmp|gif|jpe?g|ico"
            + r"|png|tiff?|mid|mp2|mp3|mp4"
            + r"|wav|avi|mov|mpeg|ram|m4v|mkv|ogg|ogv|pdf"
            + r"|ps|eps|tex|ppt|pptx|doc|docx|xls|xlsx|names"
            + r"|data|dat|exe|bz2|tar|msi|bin|7z|psd|dmg|iso"
            + r"|epub|dll|cnf|tgz|sha1"
            + r"|thmx|mso|arff|rtf|jar|csv"
            + r"|rm|smil|wmv|swf|wma|zip|rar|gz)$", parsed.path.lower())
    except Exception as e:
        write_line_to_file(FAILED_FILE, f'Invalid URL: {url}, Type: {e}')
        return False

def _get_simhash(words):   
    '''
    Get the simhash of the page.

    Collect words and hash them into 64bits. Sum each hash with weights
    to determine what the most common bit at a position was and have
    it accordingly in the simhash
    '''
    
    frequencies = _compute_word_frequencies(words)

    bits = [0] * NUM_HASH_BITS
    for word, frequency in frequencies.items():
        # get first 8 bytes of hash --> convert to int --> convert to 64 bits
        byte_hash = hashlib.sha256(word.encode('utf-8')).digest()[:8]
        int_hash = int.from_bytes(byte_hash, 'big')
        bit_hash = f'{int_hash:0{NUM_HASH_BITS}b}'

        # add if the bit is 1 and subtract if the bit is 0
        for i in range(NUM_HASH_BITS):
            bits[i] += (1 if bit_hash[i] == '1' else -1) * frequency
        
    # positive sum indices = 1, non-positive sum indices = 0
    return int(''.join('1' if bits[i] > 0 else '0' for i in range(NUM_HASH_BITS)), 2) # converted to base10 for XOR calcs

    
def _compute_word_frequencies(tokens):
    '''
    Takes in a list of tokens and returns a dict of the 
    tokens and their frequencies.
    '''
    frequencies = {}
    for token in tokens: 
        if token not in frequencies:
            frequencies[token] = 1
        else:
            frequencies[token] += 1
    return frequencies

def _is_simhash_match(page_hash):
    '''
    Returns true if the given hashes are similar to other page's hashes.

    Checks if ((# common bits) / (# total bits)) >= threshold
    Threshold for similarity is 62 bits in common, or roughly 97% similarity.
    '''
    THRESHOLD_BITS = 62
    for other_hash_line in page_hashes:
        # Counting 0 bits from XOR = counting # bits in common
        hash_xor = page_hash ^ other_hash_line
        similarity = f'{hash_xor:0{NUM_HASH_BITS}b}'.count('0')
        if similarity >= THRESHOLD_BITS:
            return True
    
    write_line_to_file(HASH_FILE, page_hash)
    page_hashes.append(page_hash)
    return False
