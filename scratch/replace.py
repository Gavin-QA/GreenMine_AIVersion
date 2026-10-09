import os
import glob

def main():
    for f in glob.glob("**/*.py", recursive=True):
        if not os.path.isfile(f):
            continue
        try:
            with open(f, 'r', encoding='utf-8') as file:
                content = file.read()
        except:
            continue
        
        if 'utils.paths' in content:
            new_content = content.replace('utils.paths', 'utils.paths')
            with open(f, 'w', encoding='utf-8') as file:
                file.write(new_content)
            print(f"Updated {f}")

if __name__ == "__main__":
    main()
