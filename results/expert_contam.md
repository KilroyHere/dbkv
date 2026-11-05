# Expert Stage 1.2: adapter SFT split vs BIRD dev

- SFT split `dbdev4_train_5160.jsonl`: 5160 records, 64 distinct schemas (no db_id field; DB = set of table names); 5160 parsed as Task/Evidence/Schema
- system prompt identical to `harness/expert/expert_system_prompt.txt`: 5160 / 5160
- **database overlap with BIRD dev's 11 DBs (table-set Jaccard ≥ 0.5 with any SFT schema): 0** []; highest Jaccard per dev DB: [('debit_card_specializing', 0.29), ('european_football_2', 0.17), ('financial', 0.17), ('codebase_community', 0.11), ('student_club', 0.06), ('superhero', 0.06), ('formula_1', 0.06), ('card_games', 0.0), ('california_schools', 0.0), ('thrombosis_prediction', 0.0), ('toxicology', 0.0)]
- **exact (normalized) question matches with BIRD dev (1534 questions): 0**; with our 150 tasks: 0
- evidence-text matches (dev evidence > 40 chars): 0; target-SQL matches with dev gold SQL: 0

Few-shot examples for arm (b) (`harness/expert/fewshot.json`, seed 0): sql-length short [attributes+business+business_attributes+business_categories+] qNone; sql-length medium [city+competitor_event+event+games+games_city+games_competito] qNone; sql-length long [relation+sales_in_weather+weather] qNone; none on a BIRD-dev schema: True
