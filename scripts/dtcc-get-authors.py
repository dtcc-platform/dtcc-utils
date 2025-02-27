#!/usr/bin/env python3
"""
Scholarly Publications Retriever

This script retrieves academic publications for a researcher by their ORCID ID.
It queries multiple scholarly databases and consolidates the results.
"""

import argparse
import json
import time
import re
import sys
from dataclasses import dataclass
from typing import Dict, List, Set, Optional, Any
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ----- Data Classes -----

@dataclass
class Publication:
    """Class for storing publication information"""
    title: str
    authors: List[str]
    year: Optional[int]
    doi: Optional[str] = None
    journal: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    publisher: Optional[str] = None
    url: Optional[str] = None
    abstract: Optional[str] = None
    citations: Optional[int] = None
    type: Optional[str] = None
    source: str = ""  # Which database provided this info
    
    def __hash__(self):
        # Use DOI for hash if available, otherwise use title+year
        if self.doi:
            return hash(self.doi.lower())
        return hash((self.title.lower(), self.year))
    
    def __eq__(self, other):
        if not isinstance(other, Publication):
            return False
        if self.doi and other.doi:
            return self.doi.lower() == other.doi.lower()
        return self.title.lower() == other.title.lower() and self.year == other.year


# ----- HTTP Client -----

def create_session():
    """Create a requests session with retry capabilities"""
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    # Set a user agent to be polite to APIs
    session.headers.update({
        "User-Agent": "PublicationRetriever/1.0 (Academic Research Script; mailto:your-email@example.com)"
    })
    return session


# ----- ORCID API -----

def get_orcid_profile(session, orcid):
    """Retrieve basic profile information from ORCID"""
    url = f"https://pub.orcid.org/v3.0/{orcid}"
    headers = {"Accept": "application/json"}
    
    try:
        response = session.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error retrieving ORCID profile: {e}", file=sys.stderr)
        return None


def get_orcid_works(session, orcid):
    """Retrieve works from ORCID"""
    url = f"https://pub.orcid.org/v3.0/{orcid}/works"
    headers = {"Accept": "application/json"}
    
    try:
        response = session.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        publications = []
        for group in data.get("group", []):
            work_summary = group.get("work-summary", [])[0]
            
            # Get title
            title = work_summary.get("title", {}).get("title", {}).get("value", "Unknown Title")
            
            # Get type
            type_info = work_summary.get("type")
            
            # Get year
            pub_date = work_summary.get("publication-date")
            year = None
            if pub_date and "year" in pub_date:
                year = int(pub_date["year"]["value"])
            
            # Get external IDs (DOI, etc.)
            doi = None
            external_ids = work_summary.get("external-ids", {}).get("external-id", [])
            for ext_id in external_ids:
                if ext_id.get("external-id-type") == "doi":
                    doi = ext_id.get("external-id-value")
            
            # Create publication object
            pub = Publication(
                title=title,
                authors=[],  # We'll need to fetch the full work to get authors
                year=year,
                doi=doi,
                type=type_info,
                source="ORCID"
            )
            publications.append(pub)
        
        return publications
    except requests.exceptions.RequestException as e:
        print(f"Error retrieving ORCID works: {e}", file=sys.stderr)
        return []


# ----- Crossref API -----

def get_crossref_publications(session, orcid):
    """Retrieve publications from Crossref using ORCID"""
    url = f"https://api.crossref.org/works?filter=orcid:{orcid}&rows=1000"
    
    try:
        response = session.get(url)
        response.raise_for_status()
        data = response.json()
        
        publications = []
        for item in data.get("message", {}).get("items", []):
            # Get title
            title = "Unknown Title"
            if "title" in item and item["title"]:
                title = item["title"][0]
            
            # Get authors
            authors = []
            for author in item.get("author", []):
                name_parts = []
                if "given" in author:
                    name_parts.append(author["given"])
                if "family" in author:
                    name_parts.append(author["family"])
                if name_parts:
                    authors.append(" ".join(name_parts))
            
            # Get year
            year = None
            if "published" in item and "date-parts" in item["published"]:
                date_parts = item["published"]["date-parts"]
                if date_parts and date_parts[0]:
                    year = date_parts[0][0]
            
            # Get journal/container
            journal = None
            if "container-title" in item and item["container-title"]:
                journal = item["container-title"][0]
            
            # Get DOI
            doi = item.get("DOI")
            
            # Get other metadata
            volume = item.get("volume")
            issue = item.get("issue")
            pages = item.get("page")
            publisher = item.get("publisher")
            url = item.get("URL")
            
            # Create publication object
            pub = Publication(
                title=title,
                authors=authors,
                year=year,
                doi=doi,
                journal=journal,
                volume=volume,
                issue=issue,
                pages=pages,
                publisher=publisher,
                url=url,
                source="Crossref"
            )
            publications.append(pub)
        
        return publications
    except requests.exceptions.RequestException as e:
        print(f"Error retrieving Crossref publications: {e}", file=sys.stderr)
        return []


# ----- Semantic Scholar API -----

def get_semantic_scholar_profile(session, orcid):
    """Retrieve author profile from Semantic Scholar using ORCID"""
    url = f"https://api.semanticscholar.org/graph/v1/author/orcid:{orcid}"
    params = {
        "fields": "name,aliases,affiliations,homepage,paperCount,citationCount,hIndex"
    }
    
    try:
        # First attempt: direct ORCID lookup
        response = session.get(url, params=params)
        
        # Handle 404 specifically (author not found)
        if response.status_code == 404:
            print(f"Author with ORCID {orcid} not found in Semantic Scholar.", file=sys.stderr)
            print("Trying alternative lookup methods...", file=sys.stderr)
            
            # Get name from ORCID profile and try to search by name
            orcid_profile = get_orcid_profile(session, orcid)
            if orcid_profile:
                first_name = orcid_profile.get("person", {}).get("name", {}).get("given-names", {}).get("value", "")
                last_name = orcid_profile.get("person", {}).get("name", {}).get("family-name", {}).get("value", "")
                
                if first_name and last_name:
                    author_name = f"{first_name} {last_name}"
                    # Try to search Semantic Scholar by author name
                    search_url = "https://api.semanticscholar.org/graph/v1/author/search"
                    search_params = {
                        "query": author_name,
                        "fields": "name,aliases,affiliations,homepage,paperCount,citationCount,hIndex"
                    }
                    
                    try:
                        search_response = session.get(search_url, params=search_params)
                        search_response.raise_for_status()
                        search_data = search_response.json()
                        
                        # If we found any matches
                        if search_data.get("data") and len(search_data["data"]) > 0:
                            print(f"Found potential Semantic Scholar profile for {author_name}", file=sys.stderr)
                            # Return the first match as the likely profile
                            return search_data["data"][0]
                    except requests.exceptions.RequestException as e:
                        print(f"Error searching Semantic Scholar by name: {e}", file=sys.stderr)
            
            # If we couldn't find the author, return None
            return None
        
        # For other errors, raise exception
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        if "404" in str(e):
            print(f"Author with ORCID {orcid} not found in Semantic Scholar.", file=sys.stderr)
            return None
        else:
            print(f"Error retrieving Semantic Scholar profile: {e}", file=sys.stderr)
            return None


def get_semantic_scholar_publications(session, author_id):
    """Retrieve publications from Semantic Scholar using author ID"""
    if not author_id:
        return []
    
    url = f"https://api.semanticscholar.org/graph/v1/author/{author_id}/papers"
    params = {
        "fields": "title,authors,year,venue,publicationVenue,journal,volume,issue,pages,externalIds,url,abstract,citationCount",
        "limit": 1000
    }
    
    try:
        response = session.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        publications = []
        for paper in data.get("data", []):
            # Get authors
            authors = [author.get("name", "") for author in paper.get("authors", [])]
            
            # Get DOI
            doi = None
            if "externalIds" in paper and "DOI" in paper["externalIds"]:
                doi = paper["externalIds"]["DOI"]
            
            # Get venue/journal
            journal = None
            if "venue" in paper and paper["venue"]:
                journal = paper["venue"]
            elif "journal" in paper and paper["journal"]:
                journal = paper["journal"]["name"]
            
            # Create publication object
            pub = Publication(
                title=paper.get("title", "Unknown Title"),
                authors=authors,
                year=paper.get("year"),
                doi=doi,
                journal=journal,
                volume=paper.get("volume"),
                issue=paper.get("issue"),
                pages=paper.get("pages"),
                url=paper.get("url"),
                abstract=paper.get("abstract"),
                citations=paper.get("citationCount"),
                source="Semantic Scholar"
            )
            publications.append(pub)
        
        return publications
    except requests.exceptions.RequestException as e:
        print(f"Error retrieving Semantic Scholar publications: {e}", file=sys.stderr)
        return []


# ----- OpenAlex API -----

def get_openalex_publications(session, orcid):
    """Retrieve publications from OpenAlex using ORCID"""
    url = f"https://api.openalex.org/works?filter=author.orcid:{orcid}"
    params = {
        "per_page": 200
    }
    
    try:
        response = session.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        publications = []
        for item in data.get("results", []):
            # Get title
            title = item.get("title", "Unknown Title")
            
            # Get authors
            authors = []
            for author in item.get("authorships", []):
                if "author" in author and "display_name" in author["author"]:
                    authors.append(author["author"]["display_name"])
            
            # Get year
            year = None
            if "publication_year" in item:
                year = item["publication_year"]
            
            # Get DOI
            doi = None
            if "doi" in item and item["doi"] is not None:
                doi = item["doi"].replace("https://doi.org/", "")
            
            # Get journal
            journal = None
            if "primary_location" in item and item["primary_location"] is not None:
                if "source" in item["primary_location"] and item["primary_location"]["source"] is not None:
                    journal = item["primary_location"]["source"].get("display_name")
            
            # Get abstract
            abstract = None
            if "abstract_inverted_index" in item:
                # OpenAlex uses an inverted index for abstracts, need to reconstruct
                inv_index = item["abstract_inverted_index"]
                if inv_index:
                    words = list(inv_index.keys())
                    positions = []
                    for word, pos_list in inv_index.items():
                        for pos in pos_list:
                            positions.append((pos, word))
                    positions.sort()
                    abstract = " ".join([p[1] for p in positions])
            
            # Get citations
            citations = item.get("cited_by_count")
            
            # Create publication object
            pub = Publication(
                title=title,
                authors=authors,
                year=year,
                doi=doi,
                journal=journal,
                abstract=abstract,
                citations=citations,
                url=item.get("primary_location", {}).get("landing_page_url"),
                source="OpenAlex"
            )
            publications.append(pub)
        
        return publications
    except requests.exceptions.RequestException as e:
        print(f"Error retrieving OpenAlex publications: {e}", file=sys.stderr)
        return []


# ----- arXiv API -----

def get_arxiv_publications(session, orcid):
    """
    Retrieve publications from arXiv
    
    Note: arXiv doesn't directly support ORCID search, 
    so we need to use author name from ORCID profile
    """
    profile = get_orcid_profile(session, orcid)
    if not profile:
        return []
    
    # Get author name from ORCID profile
    first_name = profile.get("person", {}).get("name", {}).get("given-names", {}).get("value", "")
    last_name = profile.get("person", {}).get("name", {}).get("family-name", {}).get("value", "")
    
    if not first_name or not last_name:
        print("Could not determine author name from ORCID profile", file=sys.stderr)
        return []
    
    # Format name for arXiv search (last_name, first_name)
    author_query = f"{last_name}, {first_name}"
    
    # arXiv API URL
    url = "http://export.arxiv.org/api/query"
    params = {
        "search_query": f"au:\"{author_query}\"",
        "max_results": 200
    }
    
    try:
        response = session.get(url, params=params)
        response.raise_for_status()
        
        # arXiv returns XML, we'll need to parse it
        # Using regex for simplicity (in a production environment, use an XML parser)
        entries = re.findall(r"<entry>(.*?)</entry>", response.text, re.DOTALL)
        
        publications = []
        for entry in entries:
            # Extract title
            title_match = re.search(r"<title>(.*?)</title>", entry, re.DOTALL)
            title = title_match.group(1).strip() if title_match else "Unknown Title"
            
            # Extract authors
            author_matches = re.findall(r"<author><name>(.*?)</name></author>", entry)
            authors = [author.strip() for author in author_matches]
            
            # Extract year
            published_match = re.search(r"<published>(.*?)</published>", entry)
            year = None
            if published_match:
                published_date = published_match.group(1)
                year_match = re.search(r"^(\d{4})", published_date)
                if year_match:
                    year = int(year_match.group(1))
            
            # Extract DOI if present
            doi = None
            doi_match = re.search(r"<arxiv:doi>(.*?)</arxiv:doi>", entry)
            if doi_match:
                doi = doi_match.group(1).strip()
            
            # Extract abstract
            abstract_match = re.search(r"<summary>(.*?)</summary>", entry, re.DOTALL)
            abstract = abstract_match.group(1).strip() if abstract_match else None
            
            # Extract URL
            url_match = re.search(r"<id>(.*?)</id>", entry)
            url = url_match.group(1).strip() if url_match else None
            
            # Create publication object
            pub = Publication(
                title=title,
                authors=authors,
                year=year,
                doi=doi,
                abstract=abstract,
                url=url,
                journal="arXiv",
                source="arXiv"
            )
            publications.append(pub)
        
        return publications
    except requests.exceptions.RequestException as e:
        print(f"Error retrieving arXiv publications: {e}", file=sys.stderr)
        return []


# ----- CORE API -----

def get_core_publications(session, orcid):
    """Retrieve publications from CORE using ORCID"""
    # Note: CORE API requires an API key
    # Register for free at https://core.ac.uk/services/api
    API_KEY = "YOUR_CORE_API_KEY"  # Replace with your CORE API key
    
    url = "https://api.core.ac.uk/v3/search/works"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    payload = {
        "q": f"authors.orcid:{orcid}",
        "limit": 100
    }
    
    # Check if API key is provided
    if API_KEY == "YOUR_CORE_API_KEY":
        print("CORE API key not provided. Skipping CORE search.", file=sys.stderr)
        return []
    
    try:
        response = session.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        
        publications = []
        for item in data.get("results", []):
            # Extract authors
            authors = []
            for author in item.get("authors", []):
                if "name" in author:
                    authors.append(author["name"])
            
            # Extract year
            year = item.get("yearPublished")
            
            # Extract DOI
            doi = None
            if "identifiers" in item:
                for identifier in item["identifiers"]:
                    if identifier.get("type") == "DOI":
                        doi = identifier.get("identifier")
            
            # Create publication object
            pub = Publication(
                title=item.get("title", "Unknown Title"),
                authors=authors,
                year=year,
                doi=doi,
                journal=item.get("publisher"),
                url=item.get("downloadUrl"),
                abstract=item.get("abstract"),
                source="CORE"
            )
            publications.append(pub)
        
        return publications
    except requests.exceptions.RequestException as e:
        print(f"Error retrieving CORE publications: {e}", file=sys.stderr)
        return []


# ----- Scopus API -----

def get_scopus_publications(session, orcid):
    """Retrieve publications from Scopus using ORCID with pagination"""
    # Scopus API requires an API key
    # Register at https://dev.elsevier.com and subscribe to Scopus APIs
    API_KEY = "YOUR_SCOPUS_API_KEY"  # Replace with your Scopus API key
    API_KEY= "15dc1f98cfe0f0dd91f339dd2320ab97"

    # Check if API key is provided
    if API_KEY == "YOUR_SCOPUS_API_KEY":
        print("Scopus API key not provided. Skipping Scopus search.", file=sys.stderr)
        return []
    
    url = "https://api.elsevier.com/content/search/scopus"
    headers = {
        "X-ELS-APIKey": API_KEY,
        "Accept": "application/json"
    }
    
    # Format ORCID for Scopus query
    formatted_orcid = orcid.replace("-", "")
    
    # Use a smaller count to avoid service level limitations
    # But implement pagination to get all results
    count_per_page = 25
    
    publications = []
    start_index = 0
    total_results = None
    
    print("Retrieving Scopus publications with pagination...")
    
    while True:
        # Set up parameters for this batch
        params = {
            "query": f"ORCID({formatted_orcid})",
            "count": count_per_page,
            "start": start_index,
            "view": "STANDARD"
        }
        
        try:
            # Get this batch of results
            response = session.get(url, headers=headers, params=params)
            
            if response.status_code != 200:
                print(f"Scopus API returned status code: {response.status_code}", file=sys.stderr)
                error_text = response.text[:500] if response.text else "No detailed error message"
                print(f"Response text: {error_text}", file=sys.stderr)
                
                # If this is the first request and it failed, try alternative approach
                if start_index == 0:
                    print("Trying alternative approach with Scopus Search API...", file=sys.stderr)
                    params = {
                        "query": f"ORCID({formatted_orcid})",
                        "count": 10,
                        "field": "dc:title,dc:creator,prism:publicationName,prism:coverDate,prism:doi"
                    }
                    response = session.get(url, headers=headers, params=params)
                    
                    if response.status_code != 200:
                        print(f"Alternative Scopus approach also failed: {response.status_code}", file=sys.stderr)
                        return []
                else:
                    # If a pagination request fails, return what we have so far
                    print(f"Pagination request failed. Returning {len(publications)} publications found so far.", file=sys.stderr)
                    return publications
            
            data = response.json()
            search_results = data.get("search-results", {})
            
            # Extract total results count if this is the first request
            if total_results is None:
                total_count_entry = next((item for item in search_results.get("opensearch:totalResults", []) 
                                        if isinstance(item, dict) and "@value" in item), None)
                
                if total_count_entry:
                    total_results = int(total_count_entry["@value"])
                else:
                    try:
                        # Try direct value if not a list of dictionaries
                        total_results_str = search_results.get("opensearch:totalResults", "0")
                        total_results = int(total_results_str)
                    except (ValueError, TypeError):
                        total_results = 0
                
                print(f"Total publications in Scopus: {total_results}")
            
            # Process the results from this batch
            entries = search_results.get("entry", [])
            
            batch_pubs = []
            for entry in entries:
                # Extract title (with error handling)
                title = entry.get("dc:title", "Unknown Title")
                
                # Extract authors (with error handling)
                authors = []
                if "author" in entry:
                    if isinstance(entry["author"], list):
                        for author in entry["author"]:
                            if isinstance(author, dict):
                                if "authname" in author:
                                    authors.append(author["authname"])
                                elif "given-name" in author and "surname" in author:
                                    authors.append(f"{author['given-name']} {author['surname']}")
                    elif isinstance(entry["author"], dict):  # Handle single author case
                        if "authname" in entry["author"]:
                            authors.append(entry["author"]["authname"])
                        elif "given-name" in entry["author"] and "surname" in entry["author"]:
                            authors.append(f"{entry['author']['given-name']} {entry['author']['surname']}")
                
                # Extract year (with error handling)
                year = None
                if "prism:coverDate" in entry and entry["prism:coverDate"]:
                    year_match = re.search(r"^(\d{4})", entry["prism:coverDate"])
                    if year_match:
                        year = int(year_match.group(1))
                
                # Extract DOI (with error handling)
                doi = entry.get("prism:doi")
                
                # Extract journal/source (with error handling)
                journal = entry.get("prism:publicationName")
                
                # Extract volume, issue, pages (with error handling)
                volume = entry.get("prism:volume")
                issue = entry.get("prism:issueIdentifier")
                pages = entry.get("prism:pageRange")
                
                # Extract citations if available
                citations = None
                if "citedby-count" in entry:
                    try:
                        citations = int(entry["citedby-count"])
                    except (ValueError, TypeError):
                        pass
                
                # Create publication object
                pub = Publication(
                    title=title,
                    authors=authors,
                    year=year,
                    doi=doi,
                    journal=journal,
                    volume=volume,
                    issue=issue,
                    pages=pages,
                    url=None,  # URL omitted in simplified view
                    abstract=None,  # Abstract omitted in simplified view
                    citations=citations,
                    source="Scopus"
                )
                batch_pubs.append(pub)
            
            # Add this batch to our collection
            publications.extend(batch_pubs)
            print(f"Retrieved {len(batch_pubs)} Scopus publications (batch starting at {start_index})")
            
            # Check if we need to continue pagination
            if total_results is not None and len(publications) >= total_results:
                break
                
            # If we didn't get a full page, we're likely at the end
            if len(batch_pubs) < count_per_page:
                break
                
            # Increment start index for next batch
            start_index += count_per_page
            
            # Add a small delay to avoid rate limiting
            time.sleep(0.5)
            
        except requests.exceptions.RequestException as e:
            print(f"Error retrieving Scopus publications: {e}", file=sys.stderr)
            # Return what we have so far
            return publications
    
    print(f"Completed Scopus retrieval. Found {len(publications)} publications.")
    return publications


# ----- DBLP API (for Computer Science) -----

def get_dblp_publications(session, orcid):
    """Retrieve publications from DBLP using ORCID"""
    # First, get the DBLP author ID using ORCID
    url = f"https://dblp.org/search/author/api?q=orcid%3A{orcid}&format=json"
    
    try:
        response = session.get(url)
        response.raise_for_status()
        data = response.json()
        
        authors = data.get("result", {}).get("hits", {}).get("hit", [])
        if not authors:
            return []
        
        # Get the first author's DBLP key
        author_key = authors[0].get("info", {}).get("url", "").replace("https://dblp.org/pid/", "")
        if not author_key:
            return []
        
        # Now get publications for this author
        pub_url = f"https://dblp.org/pid/{author_key}.xml"
        response = session.get(pub_url)
        response.raise_for_status()
        
        # DBLP returns XML, we'll need to parse it
        # Using regex for simplicity (in a production environment, use an XML parser)
        publications = []
        
        # Extract different types of publications (articles, inproceedings, etc.)
        publication_types = [
            "article", "inproceedings", "proceedings", "book", 
            "incollection", "phdthesis", "mastersthesis"
        ]
        
        for pub_type in publication_types:
            pattern = f"<{pub_type}[^>]*>(.*?)</{pub_type}>"
            entries = re.findall(pattern, response.text, re.DOTALL)
            
            for entry in entries:
                # Extract title
                title_match = re.search(r"<title>(.*?)</title>", entry, re.DOTALL)
                title = title_match.group(1).strip() if title_match else "Unknown Title"
                
                # Extract authors
                author_matches = re.findall(r"<author>(.*?)</author>", entry)
                authors = [author.strip() for author in author_matches]
                
                # Extract year
                year_match = re.search(r"<year>(.*?)</year>", entry)
                year = int(year_match.group(1)) if year_match else None
                
                # Extract DOI if present
                doi_match = re.search(r"<ee>https?://doi.org/(.*?)</ee>", entry)
                doi = doi_match.group(1) if doi_match else None
                
                # Extract venue/journal
                journal = None
                if pub_type == "article":
                    journal_match = re.search(r"<journal>(.*?)</journal>", entry)
                    journal = journal_match.group(1) if journal_match else None
                elif pub_type == "inproceedings":
                    booktitle_match = re.search(r"<booktitle>(.*?)</booktitle>", entry)
                    journal = booktitle_match.group(1) if booktitle_match else None
                
                # Extract URL
                url_match = re.search(r"<ee>(.*?)</ee>", entry)
                url = url_match.group(1) if url_match else None
                
                # Extract volume, number, pages
                volume_match = re.search(r"<volume>(.*?)</volume>", entry)
                volume = volume_match.group(1) if volume_match else None
                
                number_match = re.search(r"<number>(.*?)</number>", entry)
                issue = number_match.group(1) if number_match else None
                
                pages_match = re.search(r"<pages>(.*?)</pages>", entry)
                pages = pages_match.group(1) if pages_match else None
                
                # Create publication object
                pub = Publication(
                    title=title,
                    authors=authors,
                    year=year,
                    doi=doi,
                    journal=journal,
                    volume=volume,
                    issue=issue,
                    pages=pages,
                    url=url,
                    type=pub_type,
                    source="DBLP"
                )
                publications.append(pub)
        
        return publications
    except requests.exceptions.RequestException as e:
        print(f"Error retrieving DBLP publications: {e}", file=sys.stderr)
        return []


# ----- Data Consolidation -----

def merge_publications(publications_list):
    """Merge and deduplicate publications from different sources"""
    merged = {}  # Use DOI or title+year as key
    
    for pub in publications_list:
        key = pub.doi.lower() if pub.doi else f"{pub.title.lower()}_{pub.year}"
        
        if key not in merged:
            merged[key] = pub
        else:
            # Merge information, preferring non-None values
            existing = merged[key]
            
            # Update source to show where info came from
            existing.source = f"{existing.source}, {pub.source}"
            
            # Update fields if they're missing in the existing record
            if not existing.authors and pub.authors:
                existing.authors = pub.authors
            
            if not existing.journal and pub.journal:
                existing.journal = pub.journal
                
            if not existing.abstract and pub.abstract:
                existing.abstract = pub.abstract
                
            if not existing.url and pub.url:
                existing.url = pub.url
                
            if not existing.volume and pub.volume:
                existing.volume = pub.volume
                
            if not existing.issue and pub.issue:
                existing.issue = pub.issue
                
            if not existing.pages and pub.pages:
                existing.pages = pub.pages
                
            if not existing.publisher and pub.publisher:
                existing.publisher = pub.publisher
                
            if not existing.citations and pub.citations:
                existing.citations = pub.citations
                
            if not existing.type and pub.type:
                existing.type = pub.type
    
    return list(merged.values())


def format_citation(pub):
    """Format a publication as a citation string"""
    # Format authors
    author_str = ""
    if pub.authors:
        if len(pub.authors) == 1:
            author_str = pub.authors[0]
        elif len(pub.authors) == 2:
            author_str = f"{pub.authors[0]} and {pub.authors[1]}"
        else:
            author_str = f"{pub.authors[0]} et al."
    
    # Year
    year_str = f" ({pub.year})" if pub.year else ""
    
    # Title
    title_str = f". {pub.title}"
    
    # Journal and publication details
    journal_str = ""
    if pub.journal:
        journal_str = f". {pub.journal}"
        
        # Add volume, issue, pages if available
        details = []
        if pub.volume:
            details.append(f"vol. {pub.volume}")
        if pub.issue:
            details.append(f"no. {pub.issue}")
        if pub.pages:
            details.append(f"pp. {pub.pages}")
        
        if details:
            journal_str += f", {', '.join(details)}"
    
    # DOI
    doi_str = f". DOI: {pub.doi}" if pub.doi else ""
    
    # Citations
    citation_str = f". Citations: {pub.citations}" if pub.citations is not None else ""
    
    return f"{author_str}{year_str}{title_str}{journal_str}{doi_str}{citation_str}"


def save_to_json(publications, filename):
    """Save publications to a JSON file"""
    with open(filename, 'w', encoding='utf-8') as f:
        # Convert Publications to dictionaries
        pubs_dict = [vars(pub) for pub in publications]
        json.dump(pubs_dict, f, indent=2, ensure_ascii=False)


def save_to_csv(publications, filename):
    """Save publications to a CSV file"""
    import csv
    
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        fieldnames = [
            'title', 'authors', 'year', 'journal', 'volume', 'issue', 
            'pages', 'doi', 'url', 'citations', 'type', 'source'
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        
        writer.writeheader()
        for pub in publications:
            # Convert Publication to dict, with special handling for authors list
            pub_dict = vars(pub).copy()
            pub_dict['authors'] = '; '.join(pub.authors) if pub.authors else ''
            writer.writerow(pub_dict)


def save_to_bibtex(publications, filename):
    """Save publications to a BibTeX file"""
    with open(filename, 'w', encoding='utf-8') as f:
        for i, pub in enumerate(publications):
            # Generate citation key
            first_author = ""
            if pub.authors and len(pub.authors) > 0:
                first_author = pub.authors[0].split()[-1].lower()  # Last name of first author
            
            citation_key = f"{first_author}{pub.year}{i}"
            
            # Determine entry type
            entry_type = "article"
            if pub.type:
                if "conference" in pub.type.lower() or "proceedings" in pub.type.lower():
                    entry_type = "inproceedings"
                elif "book" in pub.type.lower():
                    entry_type = "book"
                elif "thesis" in pub.type.lower():
                    if "phd" in pub.type.lower():
                        entry_type = "phdthesis"
                    else:
                        entry_type = "mastersthesis"
            
            # Start entry
            f.write(f"@{entry_type}{{{citation_key},\n")
            
            # Write fields
            if pub.authors:
                authors_bibtex = " and ".join(pub.authors)
                f.write(f"  author = {{{authors_bibtex}}},\n")
            
            f.write(f"  title = {{{pub.title}}},\n")
            
            if pub.year:
                f.write(f"  year = {{{pub.year}}},\n")
            
            if pub.journal:
                journal_field = "journal" if entry_type == "article" else "booktitle"
                f.write(f"  {journal_field} = {{{pub.journal}}},\n")
            
            if pub.volume:
                f.write(f"  volume = {{{pub.volume}}},\n")
            
            if pub.issue:
                f.write(f"  number = {{{pub.issue}}},\n")
            
            if pub.pages:
                f.write(f"  pages = {{{pub.pages}}},\n")
            
            if pub.publisher:
                f.write(f"  publisher = {{{pub.publisher}}},\n")
            
            if pub.doi:
                f.write(f"  doi = {{{pub.doi}}},\n")
            
            if pub.url:
                f.write(f"  url = {{{pub.url}}},\n")
            
            # Close entry
            f.write("}\n\n")


# ----- Main Function -----

def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Retrieve academic publications using an ORCID ID")
    parser.add_argument("orcid", help="ORCID ID (format: XXXX-XXXX-XXXX-XXXX)")
    parser.add_argument("-o", "--output", help="Output format: text, json, csv, bibtex (default: text)")
    parser.add_argument("-f", "--file", help="Output file (default: publications_<orcid>.<format>)")
    parser.add_argument("-s", "--sort", help="Sort by: year, title, citations (default: year)")
    parser.add_argument("-r", "--reverse", action="store_true", help="Reverse sort order")
    args = parser.parse_args()
    
    # Validate ORCID format
    orcid_pattern = r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$"
    if not re.match(orcid_pattern, args.orcid):
        print("Invalid ORCID format. Expected: XXXX-XXXX-XXXX-XXXX", file=sys.stderr)
        return 1
    
    print(f"Retrieving publications for ORCID: {args.orcid}")
    
    # Create session
    session = create_session()
    
    # Get author info from ORCID
    profile = get_orcid_profile(session, args.orcid)
    if profile:
        first_name = profile.get("person", {}).get("name", {}).get("given-names", {}).get("value", "")
        last_name = profile.get("person", {}).get("name", {}).get("family-name", {}).get("value", "")
        print(f"Author: {first_name} {last_name}")
    
    # Collect publications from various sources
    print("Querying databases...")
    
    all_publications = []
    
    # ORCID Works
    print("Querying ORCID...")
    orcid_pubs = get_orcid_works(session, args.orcid)
    print(f"  Found {len(orcid_pubs)} publications")
    all_publications.extend(orcid_pubs)
    
    # Crossref
    print("Querying Crossref...")
    crossref_pubs = get_crossref_publications(session, args.orcid)
    print(f"  Found {len(crossref_pubs)} publications")
    all_publications.extend(crossref_pubs)
    
    # Semantic Scholar
    print("Querying Semantic Scholar...")
    ss_profile = get_semantic_scholar_profile(session, args.orcid)
    ss_author_id = ss_profile.get("authorId") if ss_profile else None
    if ss_author_id:
        ss_pubs = get_semantic_scholar_publications(session, ss_author_id)
        print(f"  Found {len(ss_pubs)} publications")
        all_publications.extend(ss_pubs)
    else:
        print("  Author not found in Semantic Scholar")
    
    # OpenAlex
    print("Querying OpenAlex...")
    openalex_pubs = get_openalex_publications(session, args.orcid)
    print(f"  Found {len(openalex_pubs)} publications")
    all_publications.extend(openalex_pubs)
    
    # arXiv
    print("Querying arXiv...")
    arxiv_pubs = get_arxiv_publications(session, args.orcid)
    print(f"  Found {len(arxiv_pubs)} publications")
    all_publications.extend(arxiv_pubs)
    
    # DBLP
    print("Querying DBLP...")
    dblp_pubs = get_dblp_publications(session, args.orcid)
    print(f"  Found {len(dblp_pubs)} publications")
    all_publications.extend(dblp_pubs)
    
    # CORE (commented out as it requires an API key)
    # print("Querying CORE...")
    # core_pubs = get_core_publications(session, args.orcid)
    # print(f"  Found {len(core_pubs)} publications")
    # all_publications.extend(core_pubs)
    
    # Scopus (commented out as it requires an API key)
    print("Querying Scopus...")
    scopus_pubs = get_scopus_publications(session, args.orcid)
    print(f"  Found {len(scopus_pubs)} publications")
    all_publications.extend(scopus_pubs)
    
    # Merge and deduplicate
    print("Merging and deduplicating results...")
    merged_pubs = merge_publications(all_publications)
    print(f"Final count: {len(merged_pubs)} unique publications")
    
    # Sort publications
    sort_key = args.sort if args.sort else "year"
    reverse = args.reverse
    
    if sort_key == "year":
        merged_pubs.sort(key=lambda x: (x.year if x.year else 0), reverse=reverse)
    elif sort_key == "title":
        merged_pubs.sort(key=lambda x: x.title.lower(), reverse=reverse)
    elif sort_key == "citations":
        merged_pubs.sort(key=lambda x: (x.citations if x.citations else 0), reverse=reverse)
    
    # Determine output format and file
    output_format = args.output if args.output else "text"
    if args.file:
        output_file = args.file
    else:
        # Remove special characters from ORCID for filename
        orcid_clean = args.orcid.replace("-", "")
        output_file = f"publications_{orcid_clean}"
        if output_format == "json":
            output_file += ".json"
        elif output_format == "csv":
            output_file += ".csv"
        elif output_format == "bibtex":
            output_file += ".bib"
        else:
            output_file += ".txt"
    
    # Output results
    if output_format == "json":
        save_to_json(merged_pubs, output_file)
        print(f"Results saved to {output_file}")
    elif output_format == "csv":
        save_to_csv(merged_pubs, output_file)
        print(f"Results saved to {output_file}")
    elif output_format == "bibtex":
        save_to_bibtex(merged_pubs, output_file)
        print(f"Results saved to {output_file}")
    else:
        # Text output (to file or stdout)
        if output_file == "stdout":
            for i, pub in enumerate(merged_pubs, 1):
                print(f"{i}. {format_citation(pub)}")
                print()
        else:
            with open(output_file, 'w', encoding='utf-8') as f:
                for i, pub in enumerate(merged_pubs, 1):
                    f.write(f"{i}. {format_citation(pub)}\n\n")
            print(f"Results saved to {output_file}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
