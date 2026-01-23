import re
import os

all_choices = []
all_descriptions = []

for root, dirs, files in os.walk('commands'):
    for file in files:
        if file.endswith('.py'):
            filepath = os.path.join(root, file)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Find all Choice(name="...") patterns
                    matches = re.findall(r'Choice\s*\(\s*name\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
                    for match in matches:
                        length = len(match)
                        all_choices.append((filepath, match, length))
                    
                    # Also check @app_commands.describe descriptions
                    # These can also have length limits
                    describe_matches = re.findall(r'@app_commands\.describe\s*\(([^)]+)\)', content, re.DOTALL)
                    for match in describe_matches:
                        # Extract key="value" pairs
                        desc_matches = re.findall(r'(\w+)\s*=\s*["\']([^"\']+)["\']', match)
                        for param_name, desc in desc_matches:
                            if len(desc) >= 25:
                                all_descriptions.append((filepath, param_name, desc, len(desc)))
            except Exception as e:
                print(f"Error reading {filepath}: {e}")

# Sort by length
all_choices.sort(key=lambda x: x[2], reverse=True)

print("Choices 20+ characters:")
for filepath, choice, length in all_choices:
    if length >= 20:
        print(f"  {filepath}: '{choice}' = {length} chars")

# Check for any >= 25
invalid_choices = [c for c in all_choices if c[2] >= 25]
if invalid_choices:
    print(f"\nINVALID: {len(invalid_choices)} choices >= 25 characters:")
    for filepath, choice, length in invalid_choices:
        print(f"  {filepath}: '{choice}' = {length} chars")
else:
    max_len = max(c[2] for c in all_choices) if all_choices else 0
    print(f"\nAll choices are < 25 characters (max: {max_len})")

# Check descriptions
if all_descriptions:
    print(f"\nDescriptions >= 25 characters:")
    for filepath, param, desc, length in sorted(all_descriptions, key=lambda x: x[3], reverse=True):
        print(f"  {filepath}: {param} = '{desc[:50]}...' ({length} chars)")
