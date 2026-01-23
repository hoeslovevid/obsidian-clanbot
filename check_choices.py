import re
import os

all_choices = []
for root, dirs, files in os.walk('commands'):
    for file in files:
        if file.endswith('.py'):
            filepath = os.path.join(root, file)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Find all Choice(name="...") patterns
                    matches = re.findall(r'Choice\(name=["\']([^"\']+)["\']', content)
                    for match in matches:
                        all_choices.append((filepath, match, len(match)))
            except Exception as e:
                print(f"Error reading {filepath}: {e}")

# Check for choices >= 25 characters
long_choices = [(f, c, l) for f, c, l in all_choices if l >= 25]

if long_choices:
    print("Choices >= 25 characters (INVALID):")
    for filepath, choice, length in sorted(long_choices, key=lambda x: x[2], reverse=True):
        print(f"  {filepath}: '{choice}' = {length} chars")
else:
    print("No choices found >= 25 characters")
    
# Also show choices that are 23-24 chars (close to limit)
close_choices = [(f, c, l) for f, c, l in all_choices if 23 <= l < 25]
if close_choices:
    print("\nChoices 23-24 characters (close to limit):")
    for filepath, choice, length in sorted(close_choices, key=lambda x: x[2], reverse=True):
        print(f"  {filepath}: '{choice}' = {length} chars")
