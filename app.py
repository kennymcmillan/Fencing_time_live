import re
import time
import pandas as pd
import requests
from bs4 import BeautifulSoup
from seleniumwire import webdriver  # Selenium Wire captures network requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
import streamlit as st

# Set Streamlit page config to wide mode
st.set_page_config(page_title="Fencing Time Live Results Scraper", layout="wide")

# ---------------- Helper Functions ----------------

def dedup_columns(columns):
    seen = {}
    new_cols = []
    for col in columns:
        if col in seen:
            seen[col] += 1
            new_cols.append(f"{col}_{seen[col]}")
        else:
            seen[col] = 0
            new_cols.append(col)
    return new_cols

def extract_full_bracket_table(html):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="elimTableau")
    if not table:
        raise Exception("Could not find the bracket table with class 'elimTableau'.")
    rows = table.find_all("tr")
    max_cols = max(len(row.find_all(["th", "td"])) for row in rows)
    header = []
    for row in rows:
        ths = row.find_all("th", recursive=False)
        if ths:
            header = [th.get_text(strip=True) for th in ths]
            break
    if len(header) < max_cols:
        header.extend([""] * (max_cols - len(header)))
    matrix = []
    header_found = False
    for row in rows:
        if not header_found and row.find_all("th", recursive=False):
            header_found = True
            continue
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

def parse_fencer(s):
    m = re.match(r'^\((\d+)\)\s*(.*?)\s+([A-Z]{3})$', s)
    if m:
        return m.group(2).strip(), m.group(1), m.group(3)
    else:
        m = re.match(r'^\((\d+)\)\s*(.*)$', s)
        if m:
            return m.group(2).strip(), m.group(1), ""
        else:
            return s, "", ""

def simple_score_extractor(cell):
    return cell.strip() if cell.strip() else "BYE"

# ---------------- Chrome Driver Initialization Function ----------------
def get_chrome_driver():
    chrome_options = ChromeOptions()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    # Set performance logging for debugging/performance insights
    chrome_options.set_capability("goog:loggingPrefs", {'performance': 'ALL'})

    #driver_version="120.0.6099.224"
    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

def extract_poules_results(pools_url):
    driver = get_chrome_driver()
    driver.get(pools_url)
    time.sleep(3)
    max_wait = 10
    interval = 1
    prev_count = len(driver.requests)
    elapsed = 0
    while elapsed < max_wait:
        time.sleep(interval)
        elapsed += interval
        current_count = len(driver.requests)
        if current_count == prev_count:
            break
        prev_count = current_count
    pool_urls = []
    for request in driver.requests:
        if request.response and "dbut=true" in request.url:
            pool_urls.append(request.url)
    driver.quit()
    pool_urls = list(dict.fromkeys(pool_urls))
    all_bout_data = []
    pool_counter = 1
    for pool_url in pool_urls:
        headers = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0.0.0"),
            "Accept": "text/html, */*; q=0.01"
        }
        response = requests.get(pool_url, headers=headers)
        if response.status_code != 200:
            pool_counter += 1
            continue
        html = response.text
        soup = BeautifulSoup(html, "html.parser")
        pool_header_tag = soup.find("h4", class_="poolNum")
        pool_number = pool_header_tag.get_text(strip=True) if pool_header_tag else f"Pool #{pool_counter}"
        pool_table = soup.find("table", class_="poolTable")
        if not pool_table:
            pool_counter += 1
            continue
        rows = pool_table.find("tbody").find_all("tr", class_="poolRow")
        if not rows:
            pool_counter += 1
            continue
        fencers = []
        nationalities = []
        results_matrix = []
        for row in rows:
            cells = row.find_all("td")
            name_tag = cells[0].find("span", class_="poolCompName")
            name = name_tag.get_text(strip=True) if name_tag else "Unknown"
            fencers.append(name)
            affil_tag = cells[0].find("span", class_="poolAffil")
            nationality = affil_tag.get_text(strip=True) if affil_tag else "Unknown"
            nationalities.append(nationality)
            bout_cells = cells[2:2+7]
            row_results = []
            for cell in bout_cells:
                span = cell.find("span")
                cell_text = span.get_text(strip=True) if span else ""
                row_results.append(cell_text)
            results_matrix.append(row_results)
        num_fencers = len(fencers)
        for i in range(num_fencers):
            for j in range(i + 1, num_fencers):
                try:
                    result_i_j = results_matrix[i][j]
                    result_j_i = results_matrix[j][i]
                except IndexError:
                    continue
                if not result_i_j or not result_j_i:
                    continue
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
                score_string = f"{score_i}-{score_j}"
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
        pool_counter += 1
    df_poules = pd.DataFrame(all_bout_data)
    summary = {}
    for idx, row in df_poules.iterrows():
        f1 = row['Fencer1_Name']
        f2 = row['Fencer2_Name']
        nat1 = row['Fencer1_Nationality']
        nat2 = row['Fencer2_Nationality']
        s1 = row['Fencer1_Score']
        s2 = row['Fencer2_Score']
        winner = row['Winner']
        if f1 not in summary:
            summary[f1] = {"Fencer": f1, "Nationality": nat1, "Victories": 0, "Defeats": 0, "TS": 0, "TR": 0}
        if f2 not in summary:
            summary[f2] = {"Fencer": f2, "Nationality": nat2, "Victories": 0, "Defeats": 0, "TS": 0, "TR": 0}
        if winner == f1:
            summary[f1]["Victories"] += 1
            summary[f2]["Defeats"] += 1
        else:
            summary[f2]["Victories"] += 1
            summary[f1]["Defeats"] += 1
        summary[f1]["TS"] += s1
        summary[f1]["TR"] += s2
        summary[f2]["TS"] += s2
        summary[f2]["TR"] += s1
    df_poules_summary = pd.DataFrame(list(summary.values()))
    df_poules_summary["Difference"] = df_poules_summary["TS"] - df_poules_summary["TR"]
    df_poules_summary = df_poules_summary.sort_values(by=["Victories", "Fencer"], ascending=[False, True])
    return df_poules, df_poules_summary

# ---------------- Streamlit App ----------------

st.title("Fencing Time Live Results Scraper")

base_url = st.text_input("Enter the base URL", "https://www.fencingtimelive.com")

if st.button("Run Scraper"):
    try:
        # --- Tableau Extraction ---
        with st.spinner("Extracting Tableau data..."):
            driver = get_chrome_driver()
            driver.get(base_url)
            time.sleep(3)
            tableau_link = WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/tableaus/scores/']"))
            )
            tableau_href = tableau_link.get_attribute("href")
            if not tableau_href.startswith("http"):
                tableau_url = "https://www.fencingtimelive.com" + tableau_href
            else:
                tableau_url = tableau_href
            driver.get(tableau_url)
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table.elimTableau"))
            )
            time.sleep(1)
            initial_html = driver.page_source
            header_initial, matrix_initial = extract_full_bracket_table(initial_html)
            header_initial = dedup_columns(header_initial)
            df_main = pd.DataFrame(matrix_initial, columns=header_initial)
            
            # Click prevBut 4 times.
            for i in range(4):
                try:
                    driver.find_element(By.ID, "prevBut").click()
                except Exception:
                    pass  # Skip exceptions and move on
                time.sleep(2)
                updated_html = driver.page_source
                header_new, matrix_new = extract_full_bracket_table(updated_html)
                header_new = dedup_columns(header_new)
                df_new = pd.DataFrame(matrix_new, columns=header_new)
                for col in df_new.columns:
                    if col not in df_main.columns or df_main[col].eq("").all():
                        series_to_add = df_new[col].reindex(range(df_main.shape[0]), fill_value="")
                        df_main[col] = series_to_add

            # Click nextBut 10 times.
            for i in range(10):
                try:
                    driver.find_element(By.ID, "nextBut").click()
                except Exception:
                    pass  # Skip exceptions and move on
                time.sleep(2)
                updated_html = driver.page_source
                header_new, matrix_new = extract_full_bracket_table(updated_html)
                header_new = dedup_columns(header_new)
                df_new = pd.DataFrame(matrix_new, columns=header_new)
                for col in df_new.columns:
                    if col not in df_main.columns or df_main[col].eq("").all():
                        series_to_add = df_new[col].reindex(range(df_main.shape[0]), fill_value="")
                        df_main[col] = series_to_add

            driver.quit()
            df_main = df_main.dropna(axis=1, how='all')
            
            # --- Build final matches table ---
            filtered_dict = {}
            for col in df_main.columns:
                filtered_series = filter_series_with_seed(df_main[col].astype(str))
                filtered_dict[col] = filtered_series
            df_filtered = pd.DataFrame({k: pd.Series(v) for k, v in filtered_dict.items()})
            rounds = list(df_filtered.columns)
            if rounds and (not rounds[-1].strip()):
                if not df_filtered[rounds[-1]].eq("").all():
                    rounds[-1] = "Winner"
                else:
                    rounds = rounds[:-1]
                    df_filtered = df_filtered.iloc[:, :-1]
            df_filtered.columns = rounds

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
                                score = ""  # Score will be filled below
                                break
                            elif candidate_seed == seed2:
                                winner = fencer2
                                score = ""
                                break
                    else:
                        winner = fencer1 if fencer1 else fencer2
                    final_matches.append({
                        "Round": round_name,
                        "Fencer1": fencer1,
                        "Fencer2": fencer2,
                        "Winner": winner,
                        "Score": score
                    })
            df_matches = pd.DataFrame(final_matches)
            
            # --- SCORE EXTRACTION using df_main ---
            score_list = []
            for col in df_main.columns[1:]:
                col_data = df_main[col].tolist()
                col_scores = []
                i = 0
                while i < len(col_data):
                    if re.match(r'^\(\d+\)', col_data[i]):
                        if i + 1 < len(col_data):
                            score = simple_score_extractor(col_data[i+1])
                        else:
                            score = "BYE"
                        col_scores.append(score)
                        i += 2
                    else:
                        i += 1
                score_list.extend(col_scores)
            cleaned_score_list = [re.sub(r'\s*Ref.*$', '', s).strip() for s in score_list]
            
            if len(cleaned_score_list) < len(df_matches):
                cleaned_score_list += [""] * (len(df_matches) - len(cleaned_score_list))
            elif len(cleaned_score_list) > len(df_matches):
                cleaned_score_list = cleaned_score_list[:len(df_matches)]
            
            df_matches['Score'] = cleaned_score_list
            
            # --- Build Fencers Table ---
            def process_fencer(cell):
                name, seed, nat = parse_fencer(cell)
                return name, seed, nat
            fencer_info = []
            for idx, row in df_matches.iterrows():
                f1_raw = row["Fencer1"]
                f2_raw = row["Fencer2"]
                name1, seed1, nat1 = process_fencer(f1_raw)
                name2, seed2, nat2 = process_fencer(f2_raw)
                df_matches.at[idx, "Fencer1"] = name1
                df_matches.at[idx, "Fencer2"] = name2
                df_matches.at[idx, "Fencer1_Nationality"] = nat1
                df_matches.at[idx, "Fencer2_Nationality"] = nat2
                fencer_info.append((name1, nat1, seed1))
                fencer_info.append((name2, nat2, seed2))
            df_fencers = pd.DataFrame(list(set(fencer_info)), columns=["Name", "Nationality", "Seed"])
            df_fencers = df_fencers[df_fencers["Nationality"].str.strip() != ""]
            df_fencers["Seed"] = df_fencers["Seed"].astype(int)
            df_fencers = df_fencers.sort_values("Seed").reset_index(drop=True)
        
        # --- Poules Extraction ---
        with st.spinner("Extracting Poules data..."):
            driver = get_chrome_driver()
            driver.get(base_url)
            time.sleep(3)
            try:
                pool_link = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "a[href*='/pools/scores/']"))
                )
                pool_link.click()
            except Exception as e:
                st.error("Could not locate the pools link element. Please verify the page layout or URL.")
                driver.quit()
                raise e
            time.sleep(3)
            pools_url = driver.current_url
            driver.quit()
            df_poules, df_poules_summary = extract_poules_results(pools_url)
        
        # --- Display Results in Tabs ---
        tab2, tab3, tab1 = st.tabs(["Tableau Results", "Fencers", "Poules Results"])
        with tab2:
            st.subheader("Tableau Matches")
            st.dataframe(df_matches)
        with tab3:
            st.subheader("Fencers")
            st.dataframe(df_fencers)
        with tab1:
            st.subheader("Poules Bout Data")
            st.dataframe(df_poules)
            st.subheader("Poules Summary")
            st.dataframe(df_poules_summary)
            
    except Exception as e:
        st.error(f"An error occurred: {e}")
