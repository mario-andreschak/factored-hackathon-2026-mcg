import asyncio
from frontend.server.conversation import Conversation
from frontend.server.voice import VoiceError,VoiceService
from frontend.tests.test_voice import audio_model,TELLS,ROUTER

async def main():
 transport,seen=audio_model(lambda body:TELLS)
 voice=VoiceService({'providers':[ROUTER]},transport=transport)
 talk=Conversation({},voice,transport=transport)
 first=[event async for event in await talk.turn('owner','es',message='Hola')]
 assert first[-1]['type']=='complete'
 assert talk._pending['owner'][0]==first[-1]['turn_id']
 assert not any(item['role']=='assistant' for item in talk._ledgers['owner'][1])
 # A rejected/lost ACK is never retried by the proposed browser fix. Let the new turn open.
 second_stream=await talk.turn('owner','es',message='Seguimos conversando')
 assert 'owner' not in talk._pending
 assert talk._active['owner']!=first[-1]['turn_id']
 assert not any(item['role']=='assistant' for item in seen[1]['messages'])
 try:talk.played('owner',first[-1]['turn_id'],first[-1]['samples'],True)
 except VoiceError as exc:assert exc.status_code==409
 else:raise AssertionError('stale prior receipt admitted')
 second=[event async for event in second_stream]
 assert not any(item['role']=='assistant' for item in talk._ledgers['owner'][1])
 try:talk.played('owner',second[-1]['turn_id'],second[-1]['samples']-1,True)
 except VoiceError as exc:assert exc.status_code==409
 else:raise AssertionError('wrong sample count admitted')
 assert not any(item['role']=='assistant' for item in talk._ledgers['owner'][1])
 talk.played('owner',second[-1]['turn_id'],second[-1]['samples'],True)
 assert [item for item in talk._ledgers['owner'][1] if item['role']=='assistant']==[{'role':'assistant','content':second[-1]['text']}]
 try:talk.played('owner',second[-1]['turn_id'],second[-1]['samples'],True)
 except VoiceError as exc:assert exc.status_code==409
 else:raise AssertionError('duplicate receipt admitted')
 await talk.close();await voice.close()
 print('Offline server semantics passed: new turn drops prior pending receipt, stale/wrong/duplicate ACK rejected, only exact current ACK appends heard assistant history; zero provider calls.')
asyncio.run(main())
