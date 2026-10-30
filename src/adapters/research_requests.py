"""Finite offline reflection over the existing authorized cumulative cost gate.

This helper DOES NOT UPLOAD FILES. Visual review may reference only file IDs
already present in recorded DeepSeek requests for the same public-film study.
Each phase has an explicit finite request count; failures are not auto-retried.
"""
from __future__ import annotations
import hashlib,json,os,re,threading,urllib.request,urllib.error
from pathlib import Path
from .deepseek_cost_gate import State,create_server
from src.motif_core.offline.experience_registry import durable


def image_content(value,file_ids=(),file_labels=None):
    if file_labels is not None and len(file_labels)!=len(file_ids):raise ValueError('image_label_count_changed')
    content=[{'type':'text','text':json.dumps(value,ensure_ascii=False)}]
    for index,file_id in enumerate(file_ids):
        if file_labels is not None:
            content.append({'type':'text','text':json.dumps(file_labels[index],ensure_ascii=False)})
        content.append({'type':'file','file_id':file_id})
    return content


class ResearchRequests:
    def __init__(self,base,output,phase,*,max_requests,max_output=2000):
        if type(max_requests) is not int or max_requests<1:raise ValueError('finite_phase_request_count_required')
        self.base=Path(base);self.output=Path(output);self.phase=phase
        self.max_output=max_output;self.max_requests=max_requests
        self.output.mkdir(parents=True,exist_ok=True);self.ids=[];self.current=phase
        self.key=os.environ.get('DEEPSEEK_API_KEY')
        if not self.key:raise ValueError('private_model_credential_required')

    def __enter__(self):
        owner=self
        class AccountedState(State):
            def log(self,row):
                super().log({**row,'experiment_id':'remotion-program-rsi-20261030-v1',
                             'phase':owner.phase,'collection_active_job':owner.current})
            def book(self,body):
                booked=super().book(body)
                if booked:
                    owner.ids.append(booked[0]);payload=json.loads(body)
                    durable(owner.base/'requests'/f'{booked[0]:06d}.json',payload,exclusive=True)
                    durable(owner.output/f'{booked[0]:06d}-request.json',payload,exclusive=True)
                return booked
        # The provider gate's counter is cumulative; the finite phase limit is
        # checked below without resetting the old counter or old paid failures.
        self.state=AccountedState(cap_usd=None,output_cap=self.max_output,record=self.base/'cost-ledger.jsonl',
                                 request_limit=None,checkpoint=self.base/'budget-checkpoint.json')
        self.gate=create_server('127.0.0.1',0,'https://api.deepseek.com',self.state)
        self.thread=threading.Thread(target=self.gate.serve_forever,daemon=True);self.thread.start()
        return self

    def ask(self,system,value,*,file_ids=(),file_labels=None,job=None):
        if len(self.ids)>=self.max_requests:raise ValueError('phase_request_count_reached')
        if any(not re.fullmatch(r'file-[A-Za-z0-9_-]+',file_id) for file_id in file_ids):raise ValueError('invalid_existing_file_reference')
        if job:self.current=self.phase+'/'+job
        if 'json' not in system.lower():system+='\nReturn JSON only.'
        content=image_content(value,file_ids,file_labels)
        payload={'model':'deepseek-flash','thinking':{'type':'disabled'},'max_tokens':self.max_output,
                 'stream':False,'response_format':{'type':'json_object'},
                 'messages':[{'role':'system','content':system},
                             {'role':'user','content':content if file_ids else content[0]['text']}]}
        request=urllib.request.Request(f'http://127.0.0.1:{self.gate.server_port}/v1/chat/completions',
            data=json.dumps(payload,ensure_ascii=False).encode(),
            headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(request,timeout=240) as response:answer=json.load(response)
        except urllib.error.HTTPError as error:
            detail=error.read(16384).decode(errors='replace').replace(self.key,'[redacted]')
            durable(self.output/f'{self.ids[-1]:06d}-http-error.json',{'status':error.code,'body':detail},exclusive=True)
            raise ValueError('research_provider_http_'+str(error.code)) from None
        durable(self.output/f'{self.ids[-1]:06d}-response.json',answer,exclusive=True)
        if answer['choices'][0]['finish_reason']!='stop':raise ValueError('research_response_incomplete')
        return json.loads(answer['choices'][0]['message']['content'])

    def __exit__(self,*errors):
        self.gate.shutdown();self.gate.server_close();self.thread.join(timeout=5)
        durable(self.output/'request-accounting.json',{'phase':self.phase,'request_ids':self.ids,
            'max_phase_requests':self.max_requests,'cumulative_requests':self.state.request_count,
            'cumulative_accounted_usd':self.state.reserved_usd,'billing_usd':None,'reset_history':False,
            'request_runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
