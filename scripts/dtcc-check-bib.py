import requests
import re

# ----------------------------
# 1. PARSE REFERENCES
# ----------------------------
def parse_reference(ref_text):
    """
    Attempts to parse an APA-like reference and extract:
    - Title
    - Year
    - Journal (or source)
    - Volume
    - Page range
    
    This function uses simple regex heuristics that may fail for more complex references.
    Adjust or improve if your references have a different or more complicated format.
    """
    # Regex patterns (very naive, might fail on complex references)
    year_pattern = r"\((\d{4})\)"
    pages_pattern = r", (\d+(?:-\d+)?)\."
    
    # Try capturing the year
    year_match = re.search(year_pattern, ref_text)
    year = year_match.group(1) if year_match else None
    
    # Try capturing pages
    pages_match = re.search(pages_pattern, ref_text)
    pages = pages_match.group(1) if pages_match else None
    
    # Split by period to get segments, then guess the title segment
    # This is simplistic—actual references can be more complicated.
    parts = [p.strip() for p in ref_text.split(".")]
    
    # The second segment in typical APA references often contains the article title
    # Example: "Aliabadi, A. A., ... (2018). Effects of roof-edge roughness on air temperature..."
    # We'll do a naive guess for the title.
    # If there's no second segment, fallback to entire string
    title = parts[1] if len(parts) > 1 else ref_text
    
    # The last part might contain the journal info
    # Example: "Boundary-Layer Meteorology, 164(2), 249-279"
    # We'll guess the last part is the "journal info"
    journal_info = parts[-1] if len(parts) > 1 else ""
    
    # We can try to separate the journal name from volume/issue
    # For instance: "Boundary-Layer Meteorology, 164(2), 249-279"
    # We'll split by comma, first part is the journal, then volume/issue, etc.
    journal_parts = journal_info.split(",")
    journal = journal_parts[0].strip() if journal_parts else journal_info
    
    # Attempt to remove leftover parentheses from the journal name
    journal = re.sub(r"\(\d+\)", "", journal).strip()
    
    parsed_ref = {
        "original_text": ref_text,
        "year": year,
        "title": title,
        "journal": journal,
        "pages": pages
    }
    return parsed_ref

# ----------------------------
# 2. CHECK VIA CROSSREF
# ----------------------------
def check_crossref(ref_dict):
    """
    Query Crossref using the article's title (and possibly other fields) to see if there's a match.
    Returns a dictionary with some info about the match or None if not found.
    """
    base_url = "https://api.crossref.org/works"
    # Build a query string. Here we’re using title + journal + year to increase chances of a match.
    query_str = f"{ref_dict['title']} {ref_dict['journal']} {ref_dict['year']}"

    params = {
        "query.bibliographic": query_str,
        "rows": 1  # we'll just ask for the top match
    }
    
    try:
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data["message"]["items"]:
            top_match = data["message"]["items"][0]
            return {
                "found": True,
                "doi": top_match.get("DOI"),
                "title": top_match.get("title", [""])[0] if top_match.get("title") else "",
                "year": top_match.get("published-print", {}).get("date-parts", [[None]])[0][0],
                "publisher": top_match.get("publisher")
            }
    except requests.RequestException as e:
        print(f"Crossref request failed for: {ref_dict['title']}. Error: {e}")
    return {"found": False}

# ----------------------------
# 3. CHECK VIA SCOPUS (requires valid API key or library)
# ----------------------------
def check_scopus(ref_dict, api_key):
    """
    Query Scopus with the article's title and/or other fields.
    This is an example using the 'Author Search' endpoint, but you might need a different endpoint.
    
    IMPORTANT: You need a valid Scopus API key. Some libraries like 'pybliometrics' can handle
    authentication and queries for you. This function shows a direct request approach.
    """
    # This is an example for demonstration only. Adjust the endpoint and parameters as needed.
    base_url = "https://api.elsevier.com/content/search/scopus"
    
    # Searching by article title and year, for instance:
    query_str = f"TITLE({ref_dict['title']}) AND PUBYEAR IS {ref_dict['year']}"
    
    headers = {
        "X-ELS-APIKey": api_key,
        "Accept": "application/json"
    }
    
    params = {
        "query": query_str,
        "count": 1  # grab just one result
    }
    
    try:
        response = requests.get(base_url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        entries = data.get("search-results", {}).get("entry", [])
        
        if entries:
            entry = entries[0]
            return {
                "found": True,
                "scopus_id": entry.get("dc:identifier"),
                "title": entry.get("dc:title"),
                "publication_name": entry.get("prism:publicationName")
            }
    except requests.RequestException as e:
        print(f"Scopus request failed for: {ref_dict['title']}. Error: {e}")
    return {"found": False}

# ----------------------------
# 4. MAIN SCRIPT
# ----------------------------
if __name__ == "__main__":
    # Example references list. Replace with file reading if you prefer.
    reference_texts = [
        "Aliabadi, A. A., Krayenhoff, E. S., Nazarian, N., Chew, L. W., Armstrong, P. R., Afshari, A., & Norford, L. K. (2018). Effects of roof-edge roughness on air temperature and pollutant concentration in urban canyons. Boundary-Layer Meteorology, 164(2), 249-279.",
        "Amorim, J. H., Valente, J., Cascão, P., Rodrigues, V., Pimentel, C., Miranda, A. I., & Borrego, C. (2013). Pedestrian exposure to air pollution in cities: Modeling the effect of roadside trees. Advances in Meteorology, 2013, 1-7.",
        # ... (add more references as needed)
    ]
    
    # Insert your Scopus API key here if you're testing Scopus lookups:
    SCOPUS_API_KEY = "YOUR_SCOPUS_API_KEY"
    
    for ref in reference_texts:
        parsed = parse_reference(ref)
        
        # Crossref check
        crossref_result = check_crossref(parsed)
        # Scopus check
        scopus_result = check_scopus(parsed, SCOPUS_API_KEY)
        
        print("Original Reference:", parsed["original_text"])
        print("Parsed Data:", parsed)
        print("Crossref Result:", crossref_result)
        print("Scopus Result:", scopus_result)
        print("-" * 80)
