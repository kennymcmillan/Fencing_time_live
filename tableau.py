import re
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
from seleniumwire import webdriver  # Selenium Wire captures network requests
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service
from webdriver_manager.microsoft import EdgeChromiumDriverManager

#####################################
# Define headers for requests
#####################################
headers = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Edge/132.0.0.0"),
    "Accept": "text/html, */*; q=0.01"
}

#####################################
# Helper functions
#####################################
def extract_full_bracket_table(html):
    """
    Parses the bracket HTML and returns a tuple (header, matrix) where:
      - header is a list of column names from the first row with <th> tags.
      - matrix is a list of rows (each row is a list of strings for each column),
        padded to the maximum number of cells found in any row.
    Blank cells are preserved.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="elimTableau")
    if not table:
        raise Exception("Could not find the bracket table with class 'elimTableau'.")
    
    rows = table.find_all("tr")
    max_cols = max(len(row.find_all(["th", "td"])) for row in rows)
    
    # Find header row: first row with <th> elements.
    header = []
    for row in rows:
        ths = row.find_all("th", recursive=False)
        if ths:
            header = [th.get_text(strip=True) for th in ths]
            break
    print("\nDEBUG: Raw header row extracted:", header)
    print("DEBUG: Maximum columns found in any row:", max_cols)
    
    if len(header) < max_cols:
        header.extend([""] * (max_cols - len(header)))
    
    matrix = []
    header_found = False
    for row in rows:
        if not header_found and row.find_all("th", recursive=False):
            header_found = True
            continue  # skip header row
        cells = row.find_all(["td", "th"], recursive=False)
        row_data = []
        for i in range(max_cols):
            if i < len(cells):
                cell_text = cells[i].get_text(separator=" ", strip=True)
            else:
                cell_text = ""
            row_data.append(cell_text)
        matrix.append(row_data)
    return header, matrix

def filter_series_with_seed(series):
    pattern = r'^\(\d+\)'
    return series[series.str.match(pattern, na=False)].reset_index(drop=True)

def extract_seed(fencer_str):
    m = re.match(r'^\((\d+)\)', fencer_str)
    return m.group(1) if m else None

def get_score_from_next_round(winner, next_round, df_main):
    """
    (This helper is from a previous version. In the final score extraction,
    we use a simpler logic below.)
    """
    if "BYE" in winner:
        return "BYE"
    if next_round not in df_main.columns or next_round == "Winner":
        return ""
    seed = extract_seed(winner)
    if not seed:
        return ""
    col_series = df_main[next_round]
    for idx, cell in col_series.items():
        if isinstance(cell, str) and cell.startswith(f"({seed})"):
            next_idx = idx + 1
            if next_idx in df_main.index:
                score_candidate = df_main.at[next_idx, next_round]
                if re.match(r'^\d{1,2}\s*-\s*\d{1,2}$', score_candidate):
                    return score_candidate
            break
    return ""

def parse_fencer(s):
    """
    Given a string like "(48) PROKHODOV Kirill KAZ", returns a tuple (clean_name, seed, nationality)
    where:
      - clean_name is the fencer's name with the seed and nationality removed,
      - seed is the number inside the parentheses,
      - nationality is the 3-letter code at the end.
    """
    m = re.match(r'^\((\d+)\)\s*(.*?)\s+([A-Z]{3})$', s)
    if m:
        return m.group(2).strip(), m.group(1), m.group(3)
    else:
        m = re.match(r'^\((\d+)\)\s*(.*)$', s)
        if m:
            return m.group(2).strip(), m.group(1), ""
        else:
            return s, "", ""

#####################################
# PART 1: Open the page and get initial table data
#####################################
edge_options = EdgeOptions()
edge_options.use_chromium = True
edge_options.add_argument("--headless")
edge_options.add_argument("--disable-gpu")
edge_service = Service(EdgeChromiumDriverManager().install())
driver = webdriver.Edge(service=edge_service, options=edge_options)

tableau_url = "https://www.fencingtimelive.com/tableaus/scores/0616226B518040E0AC71E85A2243B146/D0796928779645B18027D6F6CA3F4D65"
driver.get(tableau_url)
time.sleep(10)

initial_html = driver.page_source
header_initial, matrix_initial = extract_full_bracket_table(initial_html)
df_main = pd.DataFrame(matrix_initial, columns=header_initial)
print("\nDEBUG: INITIAL FULL BRACKET TABLE:")
print(df_main)
print("Initial shape:", df_main.shape)

#####################################
# PART 2: Press prevBut 3 times and add any new columns
#####################################
for i in range(3):
    try:
        prev_button = driver.find_element(By.ID, "prevBut")
        prev_button.click()
        print(f"Clicked 'prevBut' iteration {i+1}")
    except Exception as e:
        print(f"Error clicking 'prevBut' at iteration {i+1}: {e}")
    time.sleep(2)
    updated_html = driver.page_source
    header_new, matrix_new = extract_full_bracket_table(updated_html)
    df_new = pd.DataFrame(matrix_new, columns=header_new)
    print(f"\nDEBUG: Table after prevBut click {i+1}:")
    print(df_new)
    print("Shape:", df_new.shape)
    for col in df_new.columns:
        if col not in df_main.columns or df_main[col].eq("").all():
            print(f"Adding column '{col}' from prevBut iteration {i+1}.")
            series_to_add = df_new[col]
            if isinstance(series_to_add, pd.DataFrame):
                series_to_add = series_to_add.iloc[:, 0]
            series_to_add = series_to_add.reindex(range(df_main.shape[0]), fill_value="")
            df_main[col] = series_to_add

#####################################
# PART 3: Press nextBut 6 times and add any new columns
#####################################
for i in range(6):
    try:
        next_button = driver.find_element(By.ID, "nextBut")
        next_button.click()
        print(f"Clicked 'nextBut' iteration {i+1}")
    except Exception as e:
        print(f"Error clicking 'nextBut' at iteration {i+1}: {e}")
    time.sleep(2)
    updated_html = driver.page_source
    header_new, matrix_new = extract_full_bracket_table(updated_html)
    df_new = pd.DataFrame(matrix_new, columns=header_new)
    print(f"\nDEBUG: Table after nextBut click {i+1}:")
    print(df_new)
    print("Shape:", df_new.shape)
    for col in df_new.columns:
        if col not in df_main.columns or df_main[col].eq("").all():
            print(f"Adding column '{col}' from nextBut iteration {i+1}.")
            series_to_add = df_new[col]
            if isinstance(series_to_add, pd.DataFrame):
                series_to_add = series_to_add.iloc[:, 0]
            series_to_add = series_to_add.reindex(range(df_main.shape[0]), fill_value="")
            df_main[col] = series_to_add

driver.quit()

# Drop any columns that are entirely empty
df_main = df_main.dropna(axis=1, how='all')
df_main = df_main.loc[:, ~(df_main == "").all()]
print("\nDEBUG: COMBINED FULL BRACKET TABLE AFTER ALL BUTTON CLICKS:")
print(df_main)
print("Combined shape:", df_main.shape)

#####################################
# PART 4: Filter by Seed and Build the Final Match Table (including Score)
#####################################
filtered_dict = {}
for col in df_main.columns:
    filtered_series = filter_series_with_seed(df_main[col].astype(str))
    filtered_dict[col] = filtered_series

df_filtered = pd.DataFrame({k: pd.Series(v) for k, v in filtered_dict.items()})
print("\nFiltered Bracket Table (only rows starting with a seed):")
print(df_filtered)
print("Filtered shape:", df_filtered.shape)

# Check last column: if header is blank but has data, rename to "Winner", otherwise drop.
rounds = list(df_filtered.columns)
print("\nDEBUG: Headers before renaming last column:", rounds)
if rounds and (not rounds[-1].strip()):
    if not df_filtered[rounds[-1]].eq("").all():
        rounds[-1] = "Winner"
    else:
        print("Dropping last column because it has no data.")
        rounds = rounds[:-1]
        df_filtered = df_filtered.iloc[:, :-1]
df_filtered.columns = rounds
print("DEBUG: Final Headers:", rounds)
print("Number of rounds (columns):", len(rounds))

# Build final matches table (df_matches) from df_filtered.
final_matches = []
num_rounds = len(rounds)
for i, round_name in enumerate(rounds):
    col_values = df_filtered[round_name].dropna().tolist()
    num_matches_in_round = len(col_values) // 2
    for j in range(num_matches_in_round):
        fencer1 = col_values[2*j]
        fencer2 = col_values[2*j + 1]
        winner = ""
        score = ""
        if i + 1 < num_rounds:
            next_round = rounds[i+1]
            next_values = df_filtered[next_round].dropna().tolist()
            seed1 = extract_seed(fencer1)
            seed2 = extract_seed(fencer2)
            for candidate in next_values:
                candidate_seed = extract_seed(candidate)
                if candidate_seed == seed1:
                    winner = fencer1
                    score = get_score_from_next_round(fencer1, next_round, df_main)
                    break
                elif candidate_seed == seed2:
                    winner = fencer2
                    score = get_score_from_next_round(fencer2, next_round, df_main)
                    break
        else:
            winner = fencer1 if fencer1 else fencer2
        if "BYE" in fencer1 or "BYE" in fencer2:
            score = "BYE"
        final_matches.append({
            "Round": round_name,
            "Fencer1": fencer1,
            "Fencer2": fencer2,
            "Winner": winner,
            "Score": score
        })

df_matches = pd.DataFrame(final_matches)
print("\nFinal Matches Table BEFORE score cleanup:")
print(df_matches)

# --- SCORE EXTRACTION & CLEANUP ---
# For each column in df_main EXCEPT the first, create a list of scores
score_list = []
for col in df_main.columns[1:]:
    col_data = df_main[col].tolist()
    col_scores = []
    i = 0
    while i < len(col_data) - 1:
        cell = col_data[i]
        if re.match(r'^\(\d+\)', cell):  # if the cell starts with a seed like "(1)"
            next_cell = col_data[i+1] if (i+1) < len(col_data) else ""
            if next_cell.strip() == "":
                col_scores.append("BYE")
            else:
                col_scores.append(next_cell)
            i += 2  # skip the score cell as we've taken it
        else:
            i += 1
    print(f"DEBUG: Raw scores extracted from column '{col}':", col_scores)
    score_list.extend(col_scores)

# Clean the score strings: remove any text starting with "Ref" (including "Ref") and trim spaces.
cleaned_score_list = [re.sub(r'\s*Ref.*$', '', s).strip() for s in score_list]

print("DEBUG: Combined raw score list:", score_list)
print("DEBUG: Cleaned score list:", cleaned_score_list)
print("DEBUG: Number of cleaned scores extracted:", len(cleaned_score_list))
print("DEBUG: Number of matches in df_matches:", len(df_matches))

# Merge the cleaned score list as the 'Score' column in df_matches.
if len(cleaned_score_list) == len(df_matches):
    df_matches['Score'] = cleaned_score_list
else:
    print("WARNING: Number of cleaned scores does not match number of matches.")
    df_matches['Score'] = cleaned_score_list[:len(df_matches)]

print("\nFinal Matches Table (with cleaned Score):")
print(df_matches)

#####################################
# PART 5: Create a Fencers Table (df_fencers)
#####################################
# For the first column only, each fencer string has the nationality at the end.
# We build a dictionary of each fencer's Name, Nationality, and Seed.
fencer_info = []
def process_fencer(cell):
    name, seed, nat = parse_fencer(cell)
    return name, seed, nat

# We process both Fencer1 and Fencer2 from df_matches.
for idx, row in df_matches.iterrows():
    f1_raw = row["Fencer1"]
    f2_raw = row["Fencer2"]
    name1, seed1, nat1 = process_fencer(f1_raw)
    name2, seed2, nat2 = process_fencer(f2_raw)
    # Update df_matches with clean names
    df_matches.at[idx, "Fencer1"] = name1
    df_matches.at[idx, "Fencer2"] = name2
    df_matches.at[idx, "Fencer1_Nationality"] = nat1
    df_matches.at[idx, "Fencer2_Nationality"] = nat2
    fencer_info.append((name1, nat1, seed1))
    fencer_info.append((name2, nat2, seed2))

# Create a separate DataFrame for unique fencers.
df_fencers = pd.DataFrame(list(set(fencer_info)), columns=["Name", "Nationality", "Seed"])

# Remove rows where Nationality is blank (after stripping any spaces)
df_fencers = df_fencers[df_fencers["Nationality"].str.strip() != ""]

# Convert the Seed column to integers
df_fencers["Seed"] = df_fencers["Seed"].astype(int)

# Sort the DataFrame by Seed in ascending order and reset the index
df_fencers = df_fencers.sort_values("Seed").reset_index(drop=True)

print(df_fencers)




df_fencers = df_fencers.sort_values("Seed").reset_index(drop=True)

print("\nFinal Matches Table (with clean names and nationalities):")
print(df_matches)
print("\nFencers Table (df_fencers):")
print(df_fencers)
