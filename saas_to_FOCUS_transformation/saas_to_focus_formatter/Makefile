.PHONY: setup venv install test run-example clean help

PYTHON   := python3
VENV_DIR := venv
VENV_BIN := $(VENV_DIR)/bin

# ── Default target ─────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  saas_to_focus_formatter — available targets"
	@echo ""
	@echo "  make setup             Create venv and install dependencies"
	@echo "  make install           Install dependencies into existing venv"
	@echo "  make test              Run all 168 unit tests"
	@echo "  make run-config        Run full pipeline using config.ini  (no extra args needed)"
	@echo "  make run-example       Run the full pipeline on ../usage_report.csv (single file)"
	@echo "  make run-batch-example Run the full pipeline on ../usage_reports/ (batch folder)"
	@echo "  make clean             Remove venv and __pycache__"
	@echo ""

# ── Setup ──────────────────────────────────────────────────────────────────────
setup: venv install
	@echo ""
	@echo "  Setup complete."
	@echo "  Activate with:  source $(VENV_DIR)/bin/activate"
	@echo "  Then run:       python3 main.py --help"
	@echo ""

venv:
	$(PYTHON) -m venv $(VENV_DIR)
	@echo "  Virtual environment created at $(VENV_DIR)/"

install:
	$(VENV_BIN)/pip install --upgrade pip --quiet
	$(VENV_BIN)/pip install -r requirements.txt --quiet
	@echo "  Dependencies installed (stdlib only — nothing to download)."

# ── Tests ──────────────────────────────────────────────────────────────────────
test:
	$(PYTHON) -m unittest discover -s tests -v

# ── Config-file run (reads all paths/billing from config.ini) ──────────────────
# Edit config.ini to set your paths and billing details, then just run:
#   make run-config
run-config:
	$(PYTHON) main.py run

# ── Example run — single file ──────────────────────────────────────────────────
# Adjust --provider_name, --billing_account_id, --billing_account_name as needed.
run-example:
	$(PYTHON) main.py transform \
		--usage_report         ../usage_report.csv \
		--mapper               mappers/copilot_mapper.json \
		--cur_template         ../saas_template.csv \
		--output               ../focus_cur_output.csv \
		--provider_name        "GitHub" \
		--billing_account_id   "org-CoreStack-Engg" \
		--billing_account_name "CoreStack Engineering" \
		--billing_currency     USD \
		--region_name          "east-us"

# ── Example run — batch folder ─────────────────────────────────────────────────
# Place all CSVs in ../usage_reports/ before running.
# Output: ../focus_cur_outputs/<stem>_focus_cur.csv per input file.
run-batch-example:
	$(PYTHON) main.py run \
		--usage_dir            ../usage_reports/ \
		--output_dir           ../focus_cur_outputs/ \
		--cur_template         ../saas_template.csv \
		--provider_name        "GitHub" \
		--billing_account_id   "org-CoreStack-Engg" \
		--billing_account_name "CoreStack Engineering" \
		--billing_currency     USD

# ── Clean ──────────────────────────────────────────────────────────────────────
clean:
	rm -rf $(VENV_DIR)
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	@echo "  Cleaned."
