import json
import requests

API_URL = "http://localhost:8000/triage"
CASES_PATH = "evals/cases.json"


def main():
    with open(CASES_PATH) as f:
        cases = json.load(f)

    correct = 0
    failures = []

    for case in cases:
        res = requests.post(API_URL, json={"text": case["input"]})
        if res.status_code != 200:
            failures.append({"input": case["input"], "error": f"HTTP {res.status_code}"})
            continue

        actual = res.json().get("category")
        expected = case["expected_category"]

        if actual == expected:
            correct += 1
        else:
            failures.append({
                "input": case["input"],
                "expected": expected,
                "actual": actual,
            })

    total = len(cases)
    print(f"\nScore: {correct}/{total}\n")

    if failures:
        print("Failures:")
        for f in failures:
            print(f"  - {f}")


if __name__ == "__main__":
    main()