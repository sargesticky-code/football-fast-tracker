"""Publish the bounded capture using a short-lived workflow OIDC token."""
import json
import os
from pathlib import Path
import requests


def publish(path):
    body=json.loads(Path(path).read_text())
    if body.get('contract')!='source_observations_only_v1' or not 0<len(body.get('records',[]))<=240:
        raise ValueError('invalid_observation_batch')
    response=requests.get(os.environ['ACTIONS_ID_TOKEN_REQUEST_URL']+'&audience=fast-tracker-supabase',
                          headers={'Authorization':'bearer '+os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']},timeout=20)
    response.raise_for_status()
    token=response.json()['value']
    print('::add-mask::'+token)
    result=requests.post('https://hekqxhgjexzxnecwhyao.supabase.co/functions/v1/adviser-source-publish',
                         headers={'Authorization':'Bearer '+token},json=body,timeout=30)
    if not result.ok:
        raise RuntimeError('publication_failed_http_'+str(result.status_code))
    summary=result.json()
    print(json.dumps(summary))
    if summary.get('accepted',0)==0:
        raise RuntimeError('no_valid_observations_accepted')
    if summary.get('matched',0)==0:
        print('::warning::No verified canonical matches; source capture is not operational adviser delivery.')

if __name__=='__main__':
    publish(os.environ.get('ADVISER_OUTPUT','/tmp/adviser-source.json'))
