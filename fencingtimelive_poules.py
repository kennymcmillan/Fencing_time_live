import time
from seleniumwire import webdriver  # using seleniumwire's webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service
from webdriver_manager.microsoft import EdgeChromiumDriverManager
import pandas as pd
from bs4 import BeautifulSoup
import requests

# Configure Edge options for Chromium-based Edge
edge_options = EdgeOptions()
edge_options.use_chromium = True
edge_options.add_argument("--headless")  # Run headless
edge_options.add_argument("--disable-gpu")

# Use webdriver-manager to automatically manage the Edge driver
edge_service = Service(EdgeChromiumDriverManager().install())

# Initialize the Edge WebDriver using Selenium Wire
driver = webdriver.Edge(service=edge_service, options=edge_options)

# Load the page
url = "https://www.fencingtimelive.com/pools/scores/0616226B518040E0AC71E85A2243B146/D5659EC899FC44868606D4DEB9A02B9F"
driver.get(url)

# Wait for network activity to stabilize
max_wait = 10  # maximum seconds to wait
interval = 1   # check every 1 second
prev_count = len(driver.requests)
elapsed = 0

while elapsed < max_wait:
    time.sleep(interval)
    elapsed += interval
    current_count = len(driver.requests)
    if current_count == prev_count:
        break  # no new requests added, we assume it has stabilized
    prev_count = current_count

# Now, iterate over all network requests and save URLs containing "dbut=true"
pool_urls = []
for request in driver.requests:
    if request.response and "dbut=true" in request.url:
        pool_urls.append(request.url)

driver.quit()

print("Captured pool URLs:")
for url in pool_urls:
    print(url)

########################################################################################################################

# Remove duplicates, if any
pool_urls = list(dict.fromkeys(pool_urls))
print("Found pool URLs:")
for url in pool_urls:
    print(url)
total_pools = len(pool_urls)
print(f"\nTotal poules to process: {total_pools}\n")

# --- Step 3: Loop through each pool URL, parse the HTML, and extract bout data ---
all_bout_data = []  # List to store bout dictionaries
pool_counter = 1     # We'll label pools incrementally

for pool_url in pool_urls:
    print(f"Processing Poule {pool_counter}/{total_pools} ...")
    # Fetch the pool HTML (using requests with a simple header)
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Edge/132.0.0.0"),
        "Accept": "text/html, */*; q=0.01"
    }
    response = requests.get(pool_url, headers=headers)
    if response.status_code != 200:
        print(f"  Failed to fetch {pool_url} : HTTP {response.status_code}")
        pool_counter += 1
        continue
    html = response.text

    # Parse the HTML with BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    
    # Extract the pool number from header (if available), otherwise use our counter.
    pool_header_tag = soup.find("h4", class_="poolNum")
    if pool_header_tag:
        pool_number = pool_header_tag.get_text(strip=True)
    else:
        pool_number = f"Pool #{pool_counter}"
    
    # Locate the pool table (table with class "poolTable")
    pool_table = soup.find("table", class_="poolTable")
    if not pool_table:
        print(f"  No pool table found for {pool_url}")
        pool_counter += 1
        continue

    # Extract all rows containing fencer data (rows with class "poolRow")
    rows = pool_table.find("tbody").find_all("tr", class_="poolRow")
    if not rows:
        print(f"  No pool rows found in {pool_url}")
        pool_counter += 1
        continue

    # Prepare lists for fencer names, nationalities, and a 2D results matrix.
    fencers = []
    nationalities = []
    results_matrix = []
    
    for row in rows:
        cells = row.find_all("td")
        # Extract fencer name from first cell
        name_tag = cells[0].find("span", class_="poolCompName")
        name = name_tag.get_text(strip=True) if name_tag else "Unknown"
        fencers.append(name)
        
        # Extract nationality from the same cell (poolAffil)
        affil_tag = cells[0].find("span", class_="poolAffil")
        if affil_tag:
            nationality = affil_tag.get_text(strip=True)
        else:
            nationality = "Unknown"
        nationalities.append(nationality)
        
        # Extract bout results from the next 7 cells (skip the first two cells: name and pool position)
        bout_cells = cells[2:2+7]
        row_results = []
        for cell in bout_cells:
            span = cell.find("span")
            cell_text = span.get_text(strip=True) if span else ""
            row_results.append(cell_text)
        results_matrix.append(row_results)
    
    # Convert the bout matrix into bout data (loop over unique pairs, i < j)
    num_fencers = len(fencers)
    for i in range(num_fencers):
        for j in range(i + 1, num_fencers):
            try:
                result_i_j = results_matrix[i][j]
                result_j_i = results_matrix[j][i]
            except IndexError:
                continue

            # Skip if either cell is empty (diagonal or unplayed bout)
            if not result_i_j or not result_j_i:
                continue

            # Determine scores and winner based on the "V" (victory) or "D" (defeat) marker.
            if result_i_j.startswith("V"):
                try:
                    score_i = int(result_i_j[1:])
                    score_j = int(result_j_i[1:])
                except ValueError:
                    continue
                winner = fencers[i]
            elif result_i_j.startswith("D"):
                try:
                    score_i = int(result_i_j[1:])
                    score_j = int(result_j_i[1:])
                except ValueError:
                    continue
                winner = fencers[j]
            else:
                continue

            # Create a score string in the format "score_i-score_j"
            score_string = f"{score_i}-{score_j}"
            
            # Append bout information (including pool, fencer names, nationalities, scores, etc.)
            bout_info = {
                "PoolNumber": pool_number,
                "Fencer1_Name": fencers[i],
                "Fencer1_Nationality": nationalities[i],
                "Fencer1_Score": score_i,
                "Fencer2_Name": fencers[j],
                "Fencer2_Nationality": nationalities[j],
                "Fencer2_Score": score_j,
                "Score": score_string,
                "Winner": winner
            }
            all_bout_data.append(bout_info)
    print(f"Finished processing {pool_number}\n")
    pool_counter += 1

# --- Step 4: Create a Pandas DataFrame with all bout data ---
df_poules = pd.DataFrame(all_bout_data)
print("Poules processed!")

# Optionally, display the DataFrame
print(df_poules)

#####################################################################################################################################

summary = {}

for idx, row in df_poules.iterrows():
    # Get fencer names, nationalities and scores for the bout
    f1 = row['Fencer1_Name']
    f2 = row['Fencer2_Name']
    nat1 = row['Fencer1_Nationality']
    nat2 = row['Fencer2_Nationality']
    s1 = row['Fencer1_Score']
    s2 = row['Fencer2_Score']
    winner = row['Winner']
    
    # Initialize each fencer in the summary dictionary if not already present.
    if f1 not in summary:
        summary[f1] = {"Fencer": f1, 
                       "Nationality": nat1,
                       "Victories": 0, "Defeats": 0, "TS": 0, "TR": 0}
    if f2 not in summary:
        summary[f2] = {"Fencer": f2, 
                       "Nationality": nat2,
                       "Victories": 0, "Defeats": 0, "TS": 0, "TR": 0}
    
    # Update victories/defeats based on the winner.
    if winner == f1:
        summary[f1]["Victories"] += 1
        summary[f2]["Defeats"] += 1
    else:
        summary[f2]["Victories"] += 1
        summary[f1]["Defeats"] += 1
    
    # Update touches scored (TS) and touches received (TR)
    summary[f1]["TS"] += s1
    summary[f1]["TR"] += s2
    summary[f2]["TS"] += s2
    summary[f2]["TR"] += s1

# Convert the summary dictionary to a DataFrame.
df_poules_summary = pd.DataFrame(list(summary.values()))

# Compute the Difference column as TS minus TR.
df_poules_summary["Difference"] = df_poules_summary["TS"] - df_poules_summary["TR"]

# Sort by Victories descending, then by Fencer name ascending.
df_poules_summary = df_poules_summary.sort_values(by=["Victories", "Fencer"], ascending=[False, True])

# Display the summary DataFrame.
print(df_poules_summary)

#################################

df_poules_summary.to_csv("poules_summary.csv", index=False)
df_poules.to_csv("poules_matches.csv", index=False)

###################################

