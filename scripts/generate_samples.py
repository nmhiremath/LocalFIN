"""
Synthetic Financial Statement Generator for localfin.

Generates realistic sample CSV statements spanning multiple accounts
(Checking, Credit Card, Business) for local demos and batch ingestion tests.
"""

from pathlib import Path

SAMPLE_DIR = Path("data/samples")

STATEMENTS = {
    "chase_checking_jan2026.csv": (
        "Date,Description,Amount,Category\n"
        "2026-01-02,DIRECT DEPOSIT ACME CORP,4250.00,Income\n"
        "2026-01-03,AVALON BAY APARTMENTS RENT,-2100.00,Housing\n"
        "2026-01-05,WHOLE FOODS MARKET,-142.18,Groceries\n"
        "2026-01-08,CON EDISON ELECTRIC,-85.40,Utilities\n"
        "2026-01-12,TRADER JOES,-68.50,Groceries\n"
        "2026-01-15,STARBUCKS STORE 0842,-6.75,Coffee\n"
        "2026-01-20,METROPOLITAN TRANSIT AUTH,-34.00,Transportation\n"
        "2026-01-25,CHASE CREDIT CRD EPAY,-500.00,Credit Card Payment\n"
        "2026-01-28,VERIZON WIRELESS,-95.00,Utilities\n"
    ),
    "discover_card_feb2026.csv": (
        "Trans. Date,Description,Amount,Category\n"
        "2026-02-02,AMAZON.COM*PRIME,-14.99,Subscriptions\n"
        "2026-02-04,TARGET STORE T-1204,-84.32,Shopping\n"
        "2026-02-07,UBER *TRIP 9842,-28.50,Rideshare\n"
        "2026-02-10,NETFLIX.COM,-19.99,Subscriptions\n"
        "2026-02-14,SWEETGREEN SOHO,-18.25,Dining\n"
        "2026-02-18,SPOTIFY USA,-10.99,Subscriptions\n"
        "2026-02-22,CVS/PHARMACY #0432,-32.10,Health & Medical\n"
        "2026-02-25,CASHBACK REWARD BONUS,45.00,Rewards\n"
    ),
    "apple_card_mar2026.csv": (
        "Date,Description,Amount,Category\n"
        "2026-03-01,APPLE.COM/BILL ICLOUD,-2.99,Subscriptions\n"
        "2026-03-03,BLUE BOTTLE COFFEE,-7.50,Coffee\n"
        "2026-03-06,EQUINOX FITNESS CLUB,-280.00,Fitness\n"
        "2026-03-12,CHIPOTLE ONLINE,-16.45,Dining\n"
        "2026-03-15,WARBY PARKER,-145.00,Eyewear\n"
        "2026-03-20,PATAGONIA NYC,-189.00,Apparel\n"
        "2026-03-28,DAILY CASH BACK,12.50,Rewards\n"
    ),
    "business_expenses_q12026.csv": (
        "Date,Description,Amount,Category\n"
        "2026-01-10,AMAZON WEB SERVICES,-142.80,Cloud Infrastructure\n"
        "2026-01-15,GITHUB INC,-21.00,Developer Tools\n"
        "2026-02-01,GOOGLE WORKSPACE,-36.00,Productivity\n"
        "2026-02-15,ANTHROPIC API USAGE,-78.40,AI Services\n"
        "2026-03-01,OPENAI PLATFORM API,-94.10,AI Services\n"
        "2026-03-15,DIGITALOCEAN DROPLETS,-48.00,Cloud Infrastructure\n"
    ),
}


def generate_sample_statements() -> None:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Generating synthetic statement files in '{SAMPLE_DIR.resolve()}'...")

    for filename, content in STATEMENTS.items():
        file_path = SAMPLE_DIR / filename
        file_path.write_text(content.strip() + "\n", encoding="utf-8")
        print(
            f"  ✓ Created: {file_path.name} ({len(content.strip().splitlines()) - 1} transactions)"
        )

    print("\nGeneration complete. Test with:")
    print(f"  python -m src.cli ingest {SAMPLE_DIR}")


if __name__ == "__main__":
    generate_sample_statements()
