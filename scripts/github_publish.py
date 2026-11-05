"""Publish only after verifying the requested locally authenticated GitHub identity.

Credentials are passed in memory and never written or printed.
"""
import argparse
import json
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--owner',required=True)
    parser.add_argument('--repo',required=True)
    parser.add_argument('--create',action='store_true')
    parser.add_argument('--push',action='store_true')
    args=parser.parse_args()
    result=subprocess.run(['git','credential','fill'],input=f'protocol=https\nhost=github.com\nusername={args.owner}\n\n',
                          text=True,capture_output=True,check=False)
    if result.returncode:
        raise SystemExit('Unable to access the requested local GitHub credential; sign-in is required.')
    credential=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
    token=credential.get('password')
    if not token:
        raise SystemExit('No GitHub credential available for the requested account.')
    def api(path, data=None):
        req=urllib.request.Request('https://api.github.com'+path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
                     'User-Agent':'madrasflow-setup','X-GitHub-Api-Version':'2022-11-28',
                     'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f'GitHub API returned HTTP {error.code} for {path}') from None
    user=api('/user')
    if user['login'].lower()!=args.owner.lower():
        raise SystemExit(f"Identity mismatch: authenticated as {user['login']}; requested {args.owner}. Nothing published.")
    print('Verified GitHub identity:',user['login'])
    if args.create:
        try:
            repo=api('/user/repos',{'name':args.repo,'private':False,'auto_init':False,
                'description':'Auditable Chennai ETM demand forecasting and conditional bus service planning'})
        except RuntimeError as error:
            if 'HTTP 422' not in str(error): raise
            repo=api(f'/repos/{args.owner}/{args.repo}')
        if repo['owner']['login'].lower()!=args.owner.lower() or repo['private']:
            raise SystemExit('Repository owner or visibility does not match the request.')
        print('Repository:',repo['html_url'])
    if args.push:
        root=Path(__file__).resolve().parents[1]
        remote=f'https://github.com/{args.owner}/{args.repo}.git'
        current=subprocess.run(['git','remote','get-url','origin'],cwd=root,capture_output=True,text=True)
        if current.returncode:
            subprocess.run(['git','remote','add','origin',remote],cwd=root,check=True)
        elif current.stdout.strip()!=remote:
            raise SystemExit('Existing origin differs; refusing to overwrite it.')
        subprocess.run(['git','-c',f'credential.https://github.com.username={args.owner}',
                        'push','-u','origin','main'],cwd=root,check=True)

if __name__=='__main__': main()
