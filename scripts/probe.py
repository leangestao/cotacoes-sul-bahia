import sys,re,urllib.request,html
from bs4 import BeautifulSoup
URLS=sys.argv[1:]
for u in URLS:
    req=urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0 (cotacoes-sul-bahia bot)"})
    raw=urllib.request.urlopen(req,timeout=30).read().decode('utf-8','replace')
    s=BeautifulSoup(raw,'html.parser')
    for t in s(['script','style','noscript','svg']): t.decompose()
    txt=re.sub(r'\n\s*\n+','\n',s.get_text('\n'))
    print('=====',u,len(raw)); print(txt[:9000])
