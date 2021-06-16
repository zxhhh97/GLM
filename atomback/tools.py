import requests
import json
import os,sys
import pymongo
import datetime,pytz,time
import re

BASEDIR = os.path.abspath(os.path.dirname(__file__))
sys.path.append(os.path.abspath(os.path.dirname(BASEDIR)))

# CONFIG: a dict in config.py 
from atomback.config import CONFIG

def connect_database(DB_SERVER_URL, DATABASE_NAME):
    client = pymongo.MongoClient(DB_SERVER_URL)
    database = client[DATABASE_NAME]
    return database

def timeswitch(t,sourcetz = "utc",totype="str",targettz = "cn",strformat = "%Y-%m-%d %H:%M:%S"):
    timezone = {
        "cn":datetime.timezone(datetime.timedelta(hours=8)),
        "utc":datetime.timezone.utc
    }
    sourcetz = timezone.get(sourcetz) if sourcetz else None
    targettz = timezone.get(targettz) if targettz else sourcetz

    # transfer to datetime
    if isinstance(t,str):
        ctime = datetime.datetime.strptime(t,strformat).replace(tzinfo = sourcetz)
    elif isinstance(t,int) or isinstance(t,float):
        if t > 1e10: t=t/1000
        ctime = datetime.datetime.fromtimestamp(t).replace(tzinfo = sourcetz)

    # from datetime to target type
    if totype == "str":
        newtime = ctime.astimezone(targettz).strftime(strformat)
    elif totype == 'timestamp':
        newtime = ctime.astimezone(targettz).timestamp()
        newtime = int(newtime)
    return newtime


def cutoff_generated(x):
    end = r"<|startofpiece|>"
    segs = re.split(end,x)
    return segs[-1]

def cut_max_length(x,length):
    x = x[:min(length,len(x))]
    pattern = re.compile("[\.\?\!\"\;]")
    m = list(re.finditer(pattern, x))
    if m:
        x = x[:m[-1].span()[1]]
        return x
    else:
        return x
    
    

def replace_regex(x, remove=None): 
    x = x.strip()
    
    x = re.sub(r"\bi\b","I",x) # i -> I 
    # delete repeating single char withspace between
    x = re.sub(r"(\b\w|\W)(\s+\1){1,}", "\g<1>", x)
    x = re.sub(r"\s{1,}"," ", x) # delete redundant space
    # delete repeating words
    x = re.sub(r'\b(\w+)(\s+\1){1,}',"\g<1>",x) # repeating words
    x = re.sub(r"\s{1,}"," ", x) # delete redundant space

    # delete repeating sentences
    tmp = re.sub(r'(.+[^\s])(\s+\1){1,}',"\g<1>",x)
    while (len(x)>len(tmp)):
        x = tmp
        tmp = re.sub(r'\b(.+[^\s])(\s+\1){1,}',"\g<1>",x)
    # delete too long words
    x = re.sub(r"(\w){20,}","",x)
    x = x.replace('_',"")
    x = re.sub(r"\$\s(?=[0-9])",'\$',x)  # $ 999 -> $999
    x = re.sub(r"(?<=[a-zA-Z])\s(\'|’)\s(?=[a-zA-Z])", "'", x) # I'm ,he's 
    x = re.sub(r"(?<=[0-9])\s\.\s(?=[0-9])",".", x)        # 9 . 1-> 9.1
    x = re.sub(r"(?<=\w)\s([\.\?\!，,\:\：])\s", "\g<1> ", x) #  end . new -> end. new
    
    # upper case at the start of sentence
    x = re.sub(r"(?:^|[\.\!\?]\s?\"?\s?)([a-z])",lambda m:m.group(0).upper(),x)
    return x

class InteractDB():
    def __init__(self,db):
        config = CONFIG
        self.DBname = db
        self.DBinfo = config['DBs'][db]
        self.DB_SERVER_URL = config['DB_SERVER_URL']
        self.BOT_API = config['BOT_API']
        self.xtoken = config['X_TOKEN']
        
        
        self.DB = connect_database(self.DB_SERVER_URL,self.DBname)
        self.indata = self.DB[self.DBinfo['colname']]
        self.update_key = self.DBinfo['key']
        self.guide_prompt = self.DBinfo['guide_prompt']

    def query_docs(self, num = 100):
        query = {self.update_key:{"$exists":False}}
        cursor = self.indata.find(query).sort([("crawled_time_t",-1)]).limit(num)
        return cursor

    def update_doc(self, doc):
        _id = doc.get('_id')
        res = self.indata.update_one({"_id":_id},{"$set":doc})
        return res
    
    def process_doc(self, doc):
        if self.DBname == 'Reddit':
            content = doc.get('title')
            content = content + self.guide_prompt
            return content
        else:
            return ""

    def postprocess_generated_content(self, content, max_length=140):
        content = cutoff_generated(content)
        content = replace_regex(content, self.guide_prompt)
        
        content = cut_max_length(content, max_length)
        if content and len(content) < 20:
            return None
        return content
    
    def parse_doc(self, origin_doc, generated_content):
        now = int(time.time())
        cn_time = timeswitch(now,sourcetz = "utc",totype="str",targettz = "cn")
        new = {
            self.update_key: generated_content,
            "generate_updated_t":now,
            "generate_updated_time":cn_time}
        origin_doc.update(new)
        return origin_doc


if __name__ =="__main__":
    st1 = timeswitch(1622981802,sourcetz="utc",targettz="cn",totype='str')
    st2 = timeswitch("2021-06-06 20:16:42",sourcetz="cn",targettz="cn",totype='timestamp')
    print(st1,st2)