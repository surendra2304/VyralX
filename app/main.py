import json
import logging
import shutil
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.database import Base, engine, get_db
from app.migrations import run_additive_migrations
from app.models import AgentTask, Asset, ContentPack, PublishJob, RenderJob, Source, VideoMetric, VideoProject, utcnow
from app.schemas import AgentTaskCancelRequest, AgentTaskRequest, ContentGenerationRequest, ContentVoiceoverRequest, DiscoveryRequest, PexelsImportRequest, PexelsSearchRequest, PublishRequest, PublishResolutionRequest, RenderRequest, SourceCreate, ThumbnailRequest, UniverseTaskEnvelope, VideoProjectCreateRequest, VideoProjectRetryRequest
from app.security import require_api_key
from app.services.probe import probe_media
from app.services.discovery import discover_youtube_videos
from app.services.trends import rank_candidates
from app.services.content import generate_content_pack
from app.services.voiceover import synthesize_voiceover
from app.services.thumbnail import extract_thumbnail
from app.services.youtube_analytics import fetch_video_metrics
from app.services.peers import configured_peers, peer_health
from app.services.project_pipeline import sync_project_memory
from app.services.pexels import import_video_file, search_videos
from app.services.rights import append_stock_attribution, source_is_publishable, verified_render_sources

settings = get_settings()
settings.prepare_directories()
Base.metadata.create_all(bind=engine)
run_additive_migrations(engine)
logging.basicConfig(level=settings.log_level)
log = logging.getLogger("vyralx")

app = FastAPI(title="VyralX", version="0.2.0",
              description="Video discovery, editing, and YouTube publishing agent")


@app.get("/health")
def health():
    return {"status": "ok", "service": "vyralx", "version": app.version}


@app.get("/ready")
def ready():
    database_ok = False
    try:
        with engine.connect() as connection:
            connection.execute(select(1))
        database_ok = True
    except Exception:
        log.exception("Readiness database check failed")
    ffmpeg_ok = shutil.which(settings.ffmpeg_bin) is not None
    worker_ok = not settings.worker_required
    worker_status = "not_required"
    if settings.worker_required:
        heartbeat_path = settings.data_dir / "worker-heartbeat.json"
        try:
            heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            updated = datetime.fromisoformat(heartbeat["updated_at"])
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            age = max(0.0, (datetime.now(timezone.utc) - updated.astimezone(timezone.utc)).total_seconds())
            worker_ok = age <= settings.worker_heartbeat_timeout_seconds and heartbeat.get("state") != "stopped"
            worker_status = "healthy" if worker_ok else "stale"
        except (OSError, ValueError, KeyError, TypeError):
            worker_status = "missing"
    ready_state = database_ok and ffmpeg_ok and worker_ok
    response = {
        "status": "ready" if ready_state else "degraded",
        "database": "connected" if database_ok else "unavailable",
        "ffmpeg": ffmpeg_ok,
        "worker": worker_status,
    }
    return JSONResponse(content=response, status_code=200 if ready_state else 503)


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse("""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>VyralX Control Room</title><style>
:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,sans-serif;background:#070b12;color:#edf2ff;--panel:#101827;--line:#26354b;--muted:#9daec9;--accent:#8be0b1}
*{box-sizing:border-box}body{max-width:1440px;margin:0 auto;padding:24px}header{display:flex;justify-content:space-between;align-items:center;gap:20px;flex-wrap:wrap;border-bottom:1px solid var(--line);padding-bottom:20px}
h1{font-size:2rem;margin:0}h2{font-size:1.05rem;margin:0 0 14px}h3{font-size:.95rem;margin:0 0 10px;color:#cbd7ef}p{color:var(--muted);line-height:1.5}.sub{color:var(--muted);font-size:.88rem}.pill{border:1px solid var(--line);border-radius:999px;padding:8px 12px;color:var(--accent);font-size:.86rem}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:14px;margin:18px 0}.card{min-width:0;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px}.span{grid-column:1/-1}
label{display:block;color:#cbd7ef;font-size:.84rem;margin:10px 0 6px}input,select,textarea{width:100%;padding:10px 11px;background:#080e18;border:1px solid #34445e;border-radius:8px;color:#edf2ff;font:inherit}textarea{min-height:95px;resize:vertical}input[type=checkbox]{width:auto}button{background:var(--accent);color:#07150d;border:0;border-radius:8px;padding:10px 13px;font-weight:750;cursor:pointer;margin-top:10px}button.secondary{background:#23354e;color:#e4edff}button.warn{background:#f2c477;color:#221703}button:disabled{opacity:.5;cursor:wait}.actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.row2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.output{min-height:50px;max-height:340px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:#070c14;border:1px solid var(--line);padding:12px;border-radius:9px;color:#b7f1ce;font:12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}.notice{font-size:.82rem;color:#f0cb86}.stat{font-size:1.65rem;color:var(--accent);font-weight:800}.tablewrap{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:.87rem}td,th{text-align:left;padding:9px;border-bottom:1px solid var(--line);vertical-align:top}th{color:#bdcbe2}
@media(max-width:620px){body{padding:12px}.row2{grid-template-columns:1fr}h1{font-size:1.6rem}.card{padding:14px}}
</style></head><body>
<header><div><h1>VyralX <span style="color:var(--accent)">/ Control Room</span></h1><p>Discover, script, produce, review, publish and measure.</p></div><span class="pill" id="health">Checking service...</span></header>
<section class="card" style="margin-top:16px"><h2>Service access</h2><div class="row2"><div><label for="apiKey">API key (kept only in this browser tab session)</label><input id="apiKey" type="password" autocomplete="off" placeholder="Required outside development mode"></div><div><label>&nbsp;</label><div class="actions"><button onclick="saveKey()">Use key</button><button class="secondary" onclick="refreshAll()">Refresh dashboard</button><button class="secondary" onclick="clearKey()">Clear key</button></div></div></div><p class="sub">The dashboard does not embed secrets in HTML. Do not use development mode on a public endpoint.</p><pre class="output" id="statusOut">Loading status...</pre></section>
<div class="grid">
<section class="card span" id="projectBuilder"><h2>Automatic topic-to-video project</h2><p>One request queues original script generation through Inference, licensed Pexels scene selection/import, local narration, timed captions, FFmpeg montage, thumbnail, and a completed render ready for manual review.</p><div class="row2"><div><label for="projectTopic">Topic</label><input id="projectTopic" value="How wind turbines generate electricity" maxlength="500"></div><div><label for="projectFormat">Format</label><select id="projectFormat"><option value="shorts">Shorts (9:16)</option><option value="long">Long form (16:9)</option></select></div></div><div class="row2"><div><label for="projectDuration">Target duration (seconds)</label><input id="projectDuration" type="number" value="45" min="15" max="600"></div><div><label for="projectScenes">Stock scenes</label><select id="projectScenes"><option value="2">2 scenes</option><option value="3">3 scenes</option><option value="4" selected>4 scenes</option></select></div></div><div class="row2"><div><label for="projectAudience">Audience</label><input id="projectAudience" value="general audience" maxlength="200"></div><div><label for="projectTone">Tone</label><input id="projectTone" value="clear, energetic and factual" maxlength="200"></div></div><label><input id="projectVoiceover" type="checkbox" checked> Generate narration (default: local eSpeak; optional external TTS)</label><label><input id="projectLicense" type="checkbox"> I have reviewed the Pexels Content License and confirm the intended use is permitted.</label><div class="actions"><button onclick="createVideoProject(this)">Create full video project</button><button class="secondary" onclick="loadProjects(this)">Refresh project jobs</button></div><p class="notice">This workflow searches and imports licensed stock clips; it does not download or reuse unrelated creators' YouTube/Instagram/TikTok videos.</p><div id="projectList"></div></section>
<section class="card"><h2>1. YouTube discovery</h2><label for="ytQuery">Topic or keyword</label><input id="ytQuery" value="AI productivity" maxlength="200"><div class="row2"><div><label>Sort</label><select id="ytOrder"><option value="viewCount">Views</option><option value="date">Newest</option><option value="relevance">Relevance</option><option value="rating">Rating</option></select></div><div><label>Results</label><select id="ytCount"><option>5</option><option selected>10</option><option>15</option><option>25</option></select></div></div><button onclick="discoverYouTube(this)">Find videos</button><p class="sub">Metadata only. Discovery does not grant permission to download or repost.</p></section>
<section class="card"><h2>2. Pexels stock footage</h2><label for="pxQuery">Search stock clips</label><input id="pxQuery" value="technology workspace" maxlength="200"><div class="row2"><div><label>Orientation</label><select id="pxOrientation"><option value="portrait">Portrait</option><option value="landscape">Landscape</option><option value="square">Square</option></select></div><div><label>Results</label><select id="pxCount"><option>5</option><option selected>10</option><option>20</option><option>25</option></select></div></div><button onclick="discoverPexels(this)">Search licensed stock</button><p class="sub">Review Pexels terms and the source details before import.</p></section>
<section class="card"><h2>3. Create original script</h2><label for="topic">Video topic</label><input id="topic" value="How solar panels work" maxlength="500"><div class="row2"><div><label>Format</label><select id="format"><option value="shorts">Shorts (vertical)</option><option value="long">Long form (landscape)</option></select></div><div><label>Target seconds</label><input id="duration" type="number" value="45" min="15" max="1800"></div></div><label for="audience">Audience</label><input id="audience" value="general audience" maxlength="200"><label for="tone">Tone</label><input id="tone" value="clear, energetic and factual" maxlength="200"><button onclick="generateContent(this)">Generate content pack</button><p class="sub">Uses the real Inference task API. Output requires editor and fact-check review.</p></section>
<section class="card"><h2>4. Register a permitted source</h2><label>Title</label><input id="sourceTitle" placeholder="Source title" maxlength="300"><label>Source URL or permission record</label><input id="sourceUrl" placeholder="https://..." maxlength="2048"><div class="row2"><div><label>Platform</label><select id="sourcePlatform"><option value="manual">Manual / owned</option><option value="pexels">Pexels</option><option value="youtube">YouTube</option><option value="other">Other</option></select></div><div><label>Creator / owner</label><input id="sourceCreator" placeholder="Creator or owner" maxlength="300"></div></div><label>License name</label><input id="licenseName" placeholder="Owned / written permission / Pexels Content License" maxlength="200"><label>Permission evidence URL or reference</label><input id="permissionRef" placeholder="Link to the license or permission evidence" maxlength="2048"><label>Notes</label><textarea id="sourceNotes" placeholder="Record restrictions, attribution and reuse scope"></textarea><label><input id="rightsConfirm" type="checkbox"> I reviewed the rights evidence and confirm reuse is permitted.</label><button onclick="createSource(this)">Register source</button><p class="notice">Only mark this verified after reviewing real evidence and usage scope.</p></section>
<section class="card"><h2>5. Import local media</h2><label>Video file</label><input id="mediaFile" type="file" accept=".mp4,.mov,.mkv,.webm,.m4v,video/*"><label>Asset title</label><input id="assetTitle" placeholder="Asset title" maxlength="300"><label>Verified source ID</label><input id="assetSourceId" type="number" min="1" placeholder="Source ID (required for render rights gate)"><button onclick="uploadAsset(this)">Upload and inspect</button><p class="sub">Media size limit is configured by MAX_UPLOAD_MB. The upload is probed by FFprobe.</p></section>
<section class="card"><h2>6. Import Pexels stock</h2><label>Pexels video ID</label><input id="pexelsVideoId" type="number" min="1" placeholder="Copy from search results"><label>Video file ID</label><input id="pexelsFileId" type="number" min="1" placeholder="Choose a returned MP4 file ID"><label>Asset title (optional)</label><input id="pexelsTitle" placeholder="Stock clip title" maxlength="300"><label><input id="pexelsConfirm" type="checkbox"> I reviewed the Pexels content license for this use.</label><button onclick="importPexels(this)">Import reviewed stock clip</button></section>
<section class="card"><h2>7. Render video</h2><label>Asset ID</label><input id="renderAssetId" type="number" min="1" placeholder="Asset ID with verified source rights"><div class="row2"><div><label>Preset</label><select id="renderPreset"><option value="shorts">Shorts 9:16</option><option value="long">Landscape 16:9</option><option value="square">Square 1:1</option></select></div><div><label>Fit</label><select id="fitMode"><option value="pad">Pad</option><option value="crop">Crop</option></select></div></div><div class="row2"><div><label>Trim start (sec)</label><input id="trimStart" type="number" min="0" value="0"></div><div><label>Trim end (optional, sec)</label><input id="trimEnd" type="number" min="0" placeholder="End of source"></div></div><label>Subtitle cues (JSON array, optional)</label><textarea id="subtitleJson" placeholder='[{"start_seconds":0,"end_seconds":2.5,"text":"Opening caption"}]'></textarea><label>Content pack ID for voiceover (optional)</label><input id="voicePackId" type="number" min="1" placeholder="Generate TTS first"><button onclick="queueRender(this)">Queue render</button><p class="sub">Runs in the background. Poll the render jobs below for progress.</p></section>
<section class="card" id="publishCard"><h2>8. Publish review</h2><label>Asset ID</label><input id="publishAssetId" type="number" min="1" placeholder="Source asset ID"><label>Completed render job ID</label><input id="publishRenderId" type="number" min="1" placeholder="Completed render ID"><label>YouTube title</label><input id="publishTitle" maxlength="100" placeholder="Video title"><label>Description</label><textarea id="publishDescription" maxlength="5000" placeholder="Video description and attribution"></textarea><label>Tags (comma separated)</label><input id="publishTags" placeholder="ai, technology, education"><div class="row2"><div><label>Privacy</label><select id="privacy"><option value="private">Private</option><option value="unlisted">Unlisted</option><option value="public">Public</option></select></div><div><label>Schedule (optional)</label><input id="publishAt" type="datetime-local"></div></div><label><input id="publishRights" type="checkbox"> I verified rights and reviewed this rendered video and metadata.</label><button onclick="requestPublish(this)">Create review request</button><button class="secondary" onclick="refreshJobs(this)">Refresh jobs</button><p class="notice">The final upload requires API-side approval, a valid OAuth token and publishing enabled.</p></section>
<section class="card"><h2>9. Content and voiceover</h2><label>Content pack ID</label><input id="voiceContentId" type="number" min="1" placeholder="Content pack ID"><button onclick="generateVoiceover(this)">Generate voiceover (optional)</button><p class="sub">Requires INFERENCE_TTS_URL, model and a verified compatible TTS service.</p><label>Render job ID for thumbnail</label><input id="thumbJobId" type="number" min="1" placeholder="Completed render ID"><label>Thumbnail timestamp (sec)</label><input id="thumbTime" type="number" min="0" value="1"><button onclick="createThumbnail(this)">Create thumbnail</button></section>
<section class="card"><h2>10. YouTube performance</h2><p class="sub">Read public view, like and comment counters for VyralX-uploaded videos.</p><button onclick="refreshAnalytics(this)">Refresh YouTube metrics</button><button class="secondary" onclick="loadAnalytics(this)">Load stored metrics</button></section>
</div>
<section class="card"><h2>Job & catalog snapshot</h2><div class="actions"><button class="secondary" onclick="loadSourcesAssets(this)">Sources and assets</button><button class="secondary" onclick="refreshJobs(this)">Render and publish jobs</button><button class="secondary" onclick="loadContent(this)">Content packs</button><button class="secondary" onclick="loadAnalytics(this)">Analytics</button><button class="secondary" onclick="loadManifest(this)">Agent manifest</button><button class="secondary" onclick="loadTasks(this)">FRIDAY tasks</button></div><pre class="output" id="actionOut">Choose an operation. Responses will appear here.</pre><div id="jobTables"></div></section>
<script>
const $=id=>document.getElementById(id);
function key(){return sessionStorage.getItem('vyralxKey')||''}
function saveKey(){sessionStorage.setItem('vyralxKey',$('apiKey').value.trim());refreshAll()}
function clearKey(){sessionStorage.removeItem('vyralxKey');$('apiKey').value='';refreshAll()}
async function api(path,opts={}){
  const headers=new Headers(opts.headers||{});
  if(key())headers.set('X-API-Key',key());
  let body=opts.body;
  if(body&&typeof body==='object'&&!(body instanceof FormData)){headers.set('Content-Type','application/json');body=JSON.stringify(body)}
  const response=await fetch(path,{...opts,headers,body});
  const type=response.headers.get('content-type')||'';
  let data=type.includes('application/json')?await response.json():await response.text();
  if(!response.ok){const message=data&&data.detail?data.detail:JSON.stringify(data);throw new Error(response.status+' '+message)}
  return data;
}
function show(data){$('actionOut').textContent=typeof data==='string'?data:JSON.stringify(data,null,2)}
function asInt(id){const v=Number($(id).value);if(!Number.isInteger(v)||v<=0)throw new Error(id+' must be a positive integer');return v}
async function run(button,fn){try{if(button)button.disabled=true;const r=await fn();show(r);return r}catch(e){show({error:String(e)});return {error:String(e)}}finally{if(button)button.disabled=false}}
async function createVideoProject(button){
 return run(button,async()=>{
  if(!$('projectLicense').checked)throw new Error('Review Pexels licensing and explicitly confirm before starting a project.');
  return api('/api/projects',{method:'POST',body:{
   topic:$('projectTopic').value,video_format:$('projectFormat').value,
   target_seconds:Number($('projectDuration').value),scene_count:Number($('projectScenes').value),
   audience:$('projectAudience').value,tone:$('projectTone').value,
   confirm_pexels_license:true,use_voiceover:$('projectVoiceover').checked
  }});
 });
}
async function downloadAuthenticated(path,filename){
 const headers=new Headers();if(key())headers.set('X-API-Key',key());
 const response=await fetch(path,{headers});
 if(!response.ok)throw new Error(response.status+' '+(await response.text()));
 const blob=await response.blob();const url=URL.createObjectURL(blob);
 const link=document.createElement('a');link.href=url;link.download=filename;document.body.appendChild(link);link.click();link.remove();
 setTimeout(()=>URL.revokeObjectURL(url),30000);
}
async function loadProjects(button){
 return run(button,async()=>{
  const data=await api('/api/projects');const root=$('projectList');root.replaceChildren();
  for(const project of data.items){
   const card=document.createElement('div');card.className='card';card.style.marginTop='12px';card.style.background='#0a111c';
   const heading=document.createElement('h3');heading.textContent=project.topic+' — '+String(project.status).toUpperCase();card.appendChild(heading);
   const details=document.createElement('p');details.className='sub';details.textContent='Project #'+project.project_id+' · '+project.video_format+' · '+project.target_seconds+'s · '+(project.asset_ids||[]).length+' scene assets · attempt '+project.attempts;card.appendChild(details);
   const preview=project.content_preview||{};
   const research=document.createElement('p');research.className='sub';research.textContent='IntelX research: '+String(preview.research_status||'not_available').toUpperCase()+(preview.research_report_ids&&preview.research_report_ids.length?' · reports '+preview.research_report_ids.join(', '):'');card.appendChild(research);
   if(preview.hook){const hook=document.createElement('p');hook.textContent='Hook: '+preview.hook;card.appendChild(hook)}
   if(preview.title_options&&preview.title_options.length){const titles=document.createElement('p');titles.className='sub';titles.textContent='Title options: '+preview.title_options.join(' | ');card.appendChild(titles)}
   if(preview.script){const scriptDetails=document.createElement('details');const summary=document.createElement('summary');summary.textContent='Review generated script and scene plan';scriptDetails.appendChild(summary);const script=document.createElement('p');script.textContent=preview.script;script.style.whiteSpace='pre-wrap';scriptDetails.appendChild(script);if(preview.scene_plan&&preview.scene_plan.length){const scenes=document.createElement('ul');for(const scene of preview.scene_plan){const item=document.createElement('li');item.textContent=String(scene.timecode||'')+' — '+String(scene.visual||'')+' — '+String(scene.on_screen_text||'');scenes.appendChild(item)}scriptDetails.appendChild(scenes)}card.appendChild(scriptDetails)}
   if(preview.fact_check_notes&&preview.fact_check_notes.length){const notes=document.createElement('details');const summary=document.createElement('summary');summary.textContent='Fact-check notes (review before publishing)';notes.appendChild(summary);const list=document.createElement('ul');for(const note of preview.fact_check_notes){const item=document.createElement('li');item.textContent=note;list.appendChild(item)}notes.appendChild(list);card.appendChild(notes)}
   if(project.error){const err=document.createElement('p');err.className='notice';err.textContent=project.error;card.appendChild(err)}
   const actions=document.createElement('div');actions.className='actions';
   if(project.status==='completed'&&project.render_job_id){
    if(project.memora_write_enabled&&project.memora_memory_status!=='stored'){
     const memory=document.createElement('button');memory.className='secondary';memory.textContent='Retry private Memora sync';
     memory.onclick=async()=>{memory.disabled=true;try{show(await api('/api/projects/'+project.project_id+'/sync-memory',{method:'POST'}));await loadProjects()}catch(e){show({error:String(e)})}finally{memory.disabled=false}};actions.appendChild(memory);
    }
    const download=document.createElement('button');download.textContent='Download MP4';
    download.onclick=async()=>{download.disabled=true;try{await downloadAuthenticated(project.render_download_path,'vyralx-project-'+project.project_id+'.mp4')}catch(e){show({error:String(e)})}finally{download.disabled=false}};actions.appendChild(download);
    if(project.thumbnail_path){const thumb=document.createElement('button');thumb.className='secondary';thumb.textContent='Preview thumbnail';
     thumb.onclick=async()=>{try{const headers=new Headers();if(key())headers.set('X-API-Key',key());const response=await fetch(project.thumbnail_path,{headers});if(!response.ok)throw new Error(response.status+' '+await response.text());const url=URL.createObjectURL(await response.blob());const img=document.createElement('img');img.src=url;img.alt='Generated video thumbnail';img.style.width='100%';img.style.maxWidth='480px';img.style.display='block';img.style.marginTop='12px';img.style.borderRadius='10px';const old=card.querySelector('img');if(old){URL.revokeObjectURL(old.src);old.remove()}card.appendChild(img)}catch(e){show({error:String(e)})}};actions.appendChild(thumb);
    }
    const prep=document.createElement('button');prep.className='secondary';prep.textContent='Prepare publish review';
    prep.onclick=()=>{$('publishAssetId').value=project.primary_asset_id||'';$('publishRenderId').value=project.render_job_id||'';const preview=project.content_preview||{};$('publishTitle').value=((preview.title_options||[])[0]||project.topic||'').slice(0,100);$('publishDescription').value=preview.description||'';$('publishTags').value=(preview.tags||[]).join(', ');$('publishRights').checked=false;$('publishCard').scrollIntoView({behavior:'smooth',block:'start'})};actions.appendChild(prep);
   }else if(project.status==='failed'&&project.attempts<3){
    const retry=document.createElement('button');retry.className='warn';retry.textContent='Retry project';
    retry.onclick=async()=>{retry.disabled=true;try{show(await api('/api/projects/'+project.project_id+'/retry',{method:'POST',body:{reason:'operator_retry'}}));await loadProjects()}catch(e){show({error:String(e)})}finally{retry.disabled=false}};actions.appendChild(retry);
   }
   card.appendChild(actions);root.appendChild(card);
  }
  return {count:data.count,projects:data.items.map(p=>({id:p.project_id,status:p.status,render_job_id:p.render_job_id}))};
 });
}
async function discoverYouTube(button){return run(button,async()=>api('/api/discover',{method:'POST',body:{query:$('ytQuery').value,max_results:Number($('ytCount').value),order:$('ytOrder').value}}))}
async function discoverPexels(button){return run(button,async()=>api('/api/discover/pexels',{method:'POST',body:{query:$('pxQuery').value,max_results:Number($('pxCount').value),orientation:$('pxOrientation').value}}))}
async function generateContent(button){return run(button,async()=>api('/api/content/generate',{method:'POST',body:{topic:$('topic').value,video_format:$('format').value,target_seconds:Number($('duration').value),audience:$('audience').value,tone:$('tone').value}}))}
async function createSource(button){return run(button,async()=>{
 if(!$('rightsConfirm').checked)throw new Error('Review rights evidence and confirm it before registration');
 if(!$('licenseName').value.trim()||!$('permissionRef').value.trim())throw new Error('A license name and permission evidence reference are required');
 return api('/api/sources',{method:'POST',body:{title:$('sourceTitle').value||'Untitled source',source_url:$('sourceUrl').value,platform:$('sourcePlatform').value,creator:$('sourceCreator').value,license_name:$('licenseName').value,permission_reference:$('permissionRef').value,rights_verified:true,status:'licensed',notes:$('sourceNotes').value}});
})}
async function uploadAsset(button){return run(button,async()=>{
 const file=$('mediaFile').files[0];if(!file)throw new Error('Select a video file');
 const src=$('assetSourceId').value.trim();if(!src)throw new Error('A verified source ID is required');
 const q=new URLSearchParams({title:$('assetTitle').value||file.name,source_id:src});
 const form=new FormData();form.append('file',file);
 return api('/api/assets/upload?'+q.toString(),{method:'POST',body:form});
})}
async function importPexels(button){return run(button,async()=>{
 if(!$('pexelsConfirm').checked)throw new Error('Confirm you reviewed the license');
 return api('/api/assets/import/pexels',{method:'POST',body:{video_id:asInt('pexelsVideoId'),video_file_id:asInt('pexelsFileId'),title:$('pexelsTitle').value,confirm_license:true}});
})}
async function queueRender(button){return run(button,async()=>{
 const body={asset_id:asInt('renderAssetId'),preset:$('renderPreset').value,fit_mode:$('fitMode').value,trim_start_seconds:Number($('trimStart').value||0)};
 if($('trimEnd').value.trim())body.trim_end_seconds=Number($('trimEnd').value);
 if($('voicePackId').value.trim())body.content_pack_id=asInt('voicePackId');
 if($('subtitleJson').value.trim())body.subtitle_segments=JSON.parse($('subtitleJson').value);
 return api('/api/render',{method:'POST',body});
})}
async function requestPublish(button){return run(button,async()=>{
 if(!$('publishRights').checked)throw new Error('Review the media and metadata and confirm rights');
 const body={asset_id:asInt('publishAssetId'),render_job_id:asInt('publishRenderId'),title:$('publishTitle').value,description:$('publishDescription').value,tags:$('publishTags').value.split(',').map(x=>x.trim()).filter(Boolean),privacy_status:$('privacy').value,confirm_rights:true};
 if($('publishAt').value){body.scheduled_at=new Date($('publishAt').value).toISOString();body.privacy_status='private'}
 return api('/api/publish',{method:'POST',body});
})}
async function generateVoiceover(button){return run(button,async()=>api('/api/content/'+asInt('voiceContentId')+'/voiceover',{method:'POST'}))}
async function createThumbnail(button){return run(button,async()=>api('/api/thumbnails',{method:'POST',body:{render_job_id:asInt('thumbJobId'),timestamp_seconds:Number($('thumbTime').value||0)}}))}
async function refreshAnalytics(button){return run(button,async()=>api('/api/analytics/refresh',{method:'POST'}))}
async function loadAnalytics(button){return run(button,async()=>api('/api/analytics'))}
async function loadSourcesAssets(button){return run(button,async()=>({sources:await api('/api/sources'),assets:await api('/api/assets')}))}
async function loadContent(button){return run(button,async()=>api('/api/content'))}
async function loadManifest(button){return run(button,async()=>api('/api/agent/manifest'))}
async function loadTasks(button){return run(button,async()=>api('/api/v1/tasks'))}
async function refreshJobs(button){
 const doRefresh=async()=>{
  const result={renders:await api('/api/render'),publishes:await api('/api/publish')};
  const root=$('jobTables');root.replaceChildren();
  const renders=document.createElement('pre');renders.className='output';renders.textContent='RENDER JOBS\\n'+JSON.stringify(result.renders,null,2);root.appendChild(renders);
  const pubs=document.createElement('pre');pubs.className='output';pubs.textContent='PUBLISH JOBS\\n'+JSON.stringify(result.publishes,null,2);root.appendChild(pubs);
  const pending=result.publishes.filter(j=>j.status==='pending_approval');
  for(const job of pending){
    const btn=document.createElement('button');btn.className='warn';btn.textContent='Approve upload job '+job.id;
    btn.onclick=async()=>{if(!confirm('You reviewed render '+job.render_job_id+', title and rights for publish job '+job.id+'? Upload only proceeds if YouTube is enabled.'))return;btn.disabled=true;try{show(await api('/api/publish/'+job.id+'/execute',{method:'POST'}));await refreshJobs()}catch(e){show({error:String(e)})}finally{btn.disabled=false}};
    root.appendChild(btn);
  }
  return {render_count:result.renders.length,publish_count:result.publishes.length,pending_approval:pending.length};
 };
 if(button)return run(button,doRefresh);
 try{show(await doRefresh())}catch(e){show({error:String(e)})}
}
async function refreshAll(){
 try{const r=await fetch('/ready');const d=await r.json();$('health').textContent=d.status; $('statusOut').textContent=JSON.stringify(d,null,2)}
 catch(e){$('health').textContent='API unavailable';$('statusOut').textContent=String(e)}
}
if(key())$('apiKey').value=key();
refreshAll();
</script></body></html>""")

def _project_summary(project: VideoProject, db: Session | None = None) -> dict:
    try:
        asset_ids = json.loads(project.asset_ids_json or "[]")
    except ValueError:
        asset_ids = []
    content_preview = {}
    if db is not None and project.content_pack_id:
        content_record = db.get(ContentPack, project.content_pack_id)
        if content_record is not None:
            try:
                pack = json.loads(content_record.pack_json or "{}")
            except ValueError:
                pack = {}
            content_preview = {
                "hook": str(pack.get("hook") or "")[:1000],
                "script": str(pack.get("script") or "")[:12000],
                "scene_plan": pack.get("scene_plan", [])[:8] if isinstance(pack.get("scene_plan"), list) else [],
                "title_options": [str(value)[:100] for value in pack.get("title_options", [])[:8]],
                "description": str(pack.get("description") or "")[:4500],
                "tags": [str(value)[:100] for value in pack.get("tags", [])[:30]],
                "fact_check_notes": [str(value)[:500] for value in pack.get("fact_check_notes", [])[:20]],
                "research_status": str(pack.get("research_status") or "not_available"),
                "research_report_ids": [
                    str(item.get("report_id"))[:120]
                    for item in pack.get("intelx_research_context", [])
                    if isinstance(item, dict) and item.get("report_id")
                ][:5],
                "requires_editor_review": bool(pack.get("requires_editor_review", True)),
            }
    return {
        "project_id": project.id, "project_key": project.project_key, "topic": project.topic,
        "content_preview": content_preview,
        "auto_discover_trend": project.auto_discover_trend, "trend_query": project.trend_query,
        "trend_max_results": project.trend_max_results, "trend_source_video_id": project.trend_source_video_id,
        "trend_source_url": project.trend_source_url, "trend_score": project.trend_score,
        "video_format": project.video_format, "target_seconds": project.target_seconds,
        "audience": project.audience, "tone": project.tone, "scene_count": project.scene_count,
        "use_voiceover": project.use_voiceover, "status": project.status,
        "content_pack_id": project.content_pack_id, "asset_ids": asset_ids,
        "primary_asset_id": project.primary_asset_id, "render_job_id": project.render_job_id,
        "memora_memory_id": project.memora_memory_id or None,
        "memora_memory_status": project.memora_memory_status,
        "memora_write_enabled": settings.memora_write_enabled,
        "thumbnail_path": f"/api/projects/{project.id}/thumbnail" if project.thumbnail_path and Path(project.thumbnail_path).is_file() else None,
        "render_download_path": f"/api/render/{project.render_job_id}/download" if project.render_job_id else None,
        "error": project.error or None, "attempts": project.attempts,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "started_at": project.started_at.isoformat() if project.started_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
        "completed_at": project.completed_at.isoformat() if project.completed_at else None,
    }


@app.post("/api/projects", status_code=202, dependencies=[Depends(require_api_key)])
def create_video_project(payload: VideoProjectCreateRequest, db: Session = Depends(get_db)):
    if not payload.confirm_pexels_license:
        raise HTTPException(403, "Review https://www.pexels.com/license/ and confirm the license")
    if payload.auto_discover_trend and not settings.youtube_data_api_key:
        raise HTTPException(422, "Automatic trend discovery requires YOUTUBE_DATA_API_KEY")
    existing = db.scalar(select(VideoProject).where(VideoProject.project_key == payload.project_key))
    if existing is not None:
        same = (payload.auto_discover_trend and existing.auto_discover_trend and existing.trend_query == payload.trend_query.strip()) or (not payload.auto_discover_trend and not existing.auto_discover_trend and existing.topic == payload.topic.strip())
        same = same and existing.trend_max_results == payload.trend_max_results and existing.video_format == payload.video_format and existing.target_seconds == payload.target_seconds and existing.scene_count == payload.scene_count and existing.audience == payload.audience and existing.tone == payload.tone and existing.confirm_pexels_license == payload.confirm_pexels_license and existing.use_voiceover == payload.use_voiceover
        if not same:
            raise HTTPException(409, "project_key already exists with different settings")
        return {**_project_summary(existing, db), "idempotent_replay": True}
    project = VideoProject(project_key=payload.project_key, topic=payload.topic.strip(), auto_discover_trend=payload.auto_discover_trend, trend_query=payload.trend_query.strip(), trend_max_results=payload.trend_max_results, video_format=payload.video_format, target_seconds=payload.target_seconds, audience=payload.audience, tone=payload.tone, scene_count=payload.scene_count, confirm_pexels_license=True, use_voiceover=payload.use_voiceover, status="queued")
    db.add(project)
    db.commit()
    db.refresh(project)
    return {**_project_summary(project, db), "idempotent_replay": False}


@app.get("/api/projects", dependencies=[Depends(require_api_key)])
def list_video_projects(db: Session = Depends(get_db), limit: int = 30):
    projects = db.scalars(select(VideoProject).order_by(VideoProject.id.desc()).limit(max(1, min(limit, 100)))).all()
    return {"count": len(projects), "items": [_project_summary(p, db) for p in projects]}


@app.get("/api/projects/{project_id}", dependencies=[Depends(require_api_key)])
def get_video_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(VideoProject, project_id)
    if project is None:
        raise HTTPException(404, "Video project not found")
    return _project_summary(project, db)


@app.post("/api/projects/{project_id}/retry", dependencies=[Depends(require_api_key)])
def retry_video_project(project_id: int, payload: VideoProjectRetryRequest, db: Session = Depends(get_db)):
    project = db.get(VideoProject, project_id)
    if project is None:
        raise HTTPException(404, "Video project not found")
    if project.status != "failed":
        raise HTTPException(409, "Only failed projects can be retried")
    if project.attempts >= settings.worker_max_attempts:
        raise HTTPException(409, "Configured project retry limit has been reached")
    project.status = "queued"
    project.error = ""
    project.completed_at = None
    project.render_job_id = None
    project.thumbnail_path = ""
    project.updated_at = utcnow()
    db.commit()
    db.refresh(project)
    return _project_summary(project, db)


@app.post("/api/projects/{project_id}/sync-memory", dependencies=[Depends(require_api_key)])
def sync_video_project_memory(project_id: int, db: Session = Depends(get_db)):
    project = db.get(VideoProject, project_id)
    if project is None:
        raise HTTPException(404, "Video project not found")
    if project.status != "completed":
        raise HTTPException(409, "Only completed projects can be written to Memora")
    result = sync_project_memory(project_id, db)
    db.refresh(project)
    return {**_project_summary(project, db), "memora_sync": result}


@app.get("/api/projects/{project_id}/thumbnail", dependencies=[Depends(require_api_key)])
def download_project_thumbnail(project_id: int, db: Session = Depends(get_db)):
    project = db.get(VideoProject, project_id)
    if project is None or not project.thumbnail_path:
        raise HTTPException(404, "Project thumbnail not found")
    path = Path(project.thumbnail_path).resolve()
    if settings.render_dir.resolve() not in path.parents or not path.is_file():
        raise HTTPException(404, "Project thumbnail is unavailable")
    return FileResponse(path, media_type="image/jpeg", filename=f"{project.project_key}-thumbnail.jpg")


@app.post("/api/discover", dependencies=[Depends(require_api_key)])
def discover(payload: DiscoveryRequest):
    query = payload.query.strip()
    if not query:
        raise HTTPException(422, "query must not be blank")
    try:
        items = discover_youtube_videos(query, payload.max_results, payload.order)
    except Exception as exc:
        log.error("YouTube discovery failed (error_type=%s)", type(exc).__name__)
        raise HTTPException(502, "YouTube discovery failed; check server logs and provider configuration") from None
    # Results are leads only: no media is downloaded and rights remain unverified.
    ranked = rank_candidates(items)
    return {"query": query, "count": len(ranked), "items": ranked, "score_note": "heuristic ranking; discovery is not permission"}


@app.post("/api/sources", dependencies=[Depends(require_api_key)])
def create_source(payload: SourceCreate, db: Session = Depends(get_db)):
    source = Source(**payload.model_dump())
    db.add(source)
    db.commit()
    db.refresh(source)
    return {"id": source.id, "status": source.status, "rights_verified": source.rights_verified}


@app.get("/api/sources", dependencies=[Depends(require_api_key)])
def list_sources(db: Session = Depends(get_db)):
    rows = db.scalars(select(Source).order_by(Source.id.desc()).limit(200)).all()
    return [{"id": s.id, "title": s.title, "source_url": s.source_url, "platform": s.platform,
             "creator": s.creator, "license_name": s.license_name,
             "permission_reference": s.permission_reference, "rights_verified": s.rights_verified,
             "status": s.status, "notes": s.notes}
            for s in rows]


@app.post("/api/assets/upload", dependencies=[Depends(require_api_key)])
async def upload_asset(file: UploadFile = File(...), title: str = "Untitled asset",
                       source_id: int | None = None, db: Session = Depends(get_db)):
    allowed = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(415, "Unsupported media extension")
    source = db.get(Source, source_id) if source_id else None
    if source_id and source is None:
        raise HTTPException(404, "Source not found")
    if source and not source_is_publishable(source):
        raise HTTPException(403, "Source rights are not verified with a license or permission reference")
    destination = (settings.media_dir / (uuid4().hex + suffix)).resolve()
    if settings.media_dir.resolve() not in destination.parents:
        raise HTTPException(400, "Invalid media path")
    max_bytes = settings.max_upload_mb * 1024 * 1024
    size = 0
    try:
        with destination.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(413, "Upload exceeds MAX_UPLOAD_MB")
                target.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    try:
        meta = await run_in_threadpool(probe_media, destination)
    except Exception as exc:
        destination.unlink(missing_ok=True)
        log.error("Media probe failed (error_type=%s)", type(exc).__name__)
        raise HTTPException(422, "Media probe failed; upload a valid video file") from None
    if meta["width"] <= 0 or meta["height"] <= 0 or meta["duration_seconds"] <= 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(422, "Uploaded file must contain a readable video stream with positive duration")
    asset = Asset(source_id=source_id, title=title[:300], file_path=str(destination),
                  rights_verified=bool(source and source_is_publishable(source)), **meta)
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return {"id": asset.id, "title": asset.title, **meta, "rights_verified": asset.rights_verified}


@app.get("/api/assets", dependencies=[Depends(require_api_key)])
def list_assets(db: Session = Depends(get_db)):
    rows = db.scalars(select(Asset).order_by(Asset.id.desc()).limit(200)).all()
    return [{"id": a.id, "title": a.title, "duration_seconds": a.duration_seconds,
             "width": a.width, "height": a.height, "rights_verified": a.rights_verified}
            for a in rows]


@app.post("/api/render", status_code=202, dependencies=[Depends(require_api_key)])
def create_render(payload: RenderRequest, db: Session = Depends(get_db)):
    asset = db.get(Asset, payload.asset_id)
    if asset is None:
        raise HTTPException(404, "Asset not found")
    source = db.get(Source, asset.source_id) if asset.source_id else None
    if not asset.rights_verified or not source_is_publishable(source):
        raise HTTPException(403, "Asset requires a verified license or permission record")
    if asset.duration_seconds <= 0:
        raise HTTPException(422, "Asset duration could not be verified by FFprobe")
    clip_end = payload.trim_end_seconds if payload.trim_end_seconds is not None else asset.duration_seconds
    if clip_end > asset.duration_seconds + 0.05:
        raise HTTPException(422, "trim_end_seconds exceeds the source media duration")
    clip_length = clip_end - payload.trim_start_seconds
    if clip_length <= 0:
        raise HTTPException(422, "Trim range has no positive duration")
    if clip_length > settings.max_render_seconds:
        raise HTTPException(422, "Requested render exceeds MAX_RENDER_SECONDS")
    for segment in payload.subtitle_segments:
        if segment.end_seconds > clip_length:
            raise HTTPException(422, "Subtitle times must fit inside the trimmed clip")
    options = payload.model_dump(mode="json", exclude={"asset_id", "preset", "content_pack_id"})
    if payload.content_pack_id is not None:
        pack = db.get(ContentPack, payload.content_pack_id)
        if pack is None:
            raise HTTPException(404, "Content pack not found")
        if pack.voiceover_status != "ready" or not pack.voiceover_path:
            raise HTTPException(409, "Generate the content pack voiceover before attaching it to a render")
        voice_path = Path(pack.voiceover_path).resolve()
        if settings.media_dir.resolve() not in voice_path.parents or not voice_path.is_file():
            raise HTTPException(409, "Generated voiceover is missing or outside media storage")
        options["voiceover_path"] = str(voice_path)
    job = RenderJob(
        asset_id=asset.id,
        preset=payload.preset,
        status="queued",
        options_json=json.dumps(options, ensure_ascii=False),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return {
        "job_id": job.id,
        "status": job.status,
        "message": "Queued for the VyralX worker; poll GET /api/render for status",
    }


@app.get("/api/render/{job_id}/download", dependencies=[Depends(require_api_key)])
def download_render(job_id: int, db: Session = Depends(get_db)):
    job = db.get(RenderJob, job_id)
    if job is None or job.status != "completed" or not job.output_path:
        raise HTTPException(404, "Completed render is unavailable")
    path = Path(job.output_path).resolve()
    if settings.render_dir.resolve() not in path.parents or not path.is_file():
        raise HTTPException(404, "Rendered video file is unavailable")
    return FileResponse(path, media_type="video/mp4", filename=f"vyralx-render-{job.id}.mp4")

@app.get("/api/render", dependencies=[Depends(require_api_key)])
def list_renders(db: Session = Depends(get_db)):
    rows = db.scalars(select(RenderJob).order_by(RenderJob.id.desc()).limit(100)).all()
    return [{"id": j.id, "asset_id": j.asset_id, "preset": j.preset, "status": j.status,
             "output_path": j.output_path, "attempts": j.attempts, "error": j.error,
             "created_at": j.created_at, "started_at": j.started_at,
             "completed_at": j.completed_at} for j in rows]


@app.post("/api/publish", dependencies=[Depends(require_api_key)])
def queue_publish(payload: PublishRequest, db: Session = Depends(get_db)):
    asset = db.get(Asset, payload.asset_id)
    if asset is None:
        raise HTTPException(404, "Asset not found")
    if not payload.confirm_rights or not asset.rights_verified:
        raise HTTPException(403, "Explicit rights confirmation and a verified source record are required")
    render = db.get(RenderJob, payload.render_job_id)
    if (
        render is None
        or render.asset_id != asset.id
        or render.status != "completed"
        or not Path(render.output_path).is_file()
    ):
        raise HTTPException(409, "Select a completed render belonging to this asset")
    privacy_status = payload.privacy_status or settings.youtube_default_privacy
    if payload.scheduled_at and privacy_status != "private":
        raise HTTPException(422, "Scheduled YouTube videos must use private privacy with publishAt")
    scheduled_at = payload.scheduled_at.isoformat().replace("+00:00", "Z") if payload.scheduled_at else ""
    source = db.get(Source, asset.source_id) if asset.source_id else None
    if not source_is_publishable(source):
        raise HTTPException(403, "Current source record does not contain verified rights evidence")
    try:
        render_sources = verified_render_sources(render, db)
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from None
    publish_description = append_stock_attribution(payload.description, render_sources)
    job = PublishJob(asset_id=asset.id, render_job_id=render.id, title=payload.title,
                     description=publish_description, tags_json=json.dumps(payload.tags[:30]),
                     privacy_status=privacy_status, scheduled_at=scheduled_at, status="pending_approval")
    db.add(job)
    db.commit()
    db.refresh(job)
    return {"job_id": job.id, "status": job.status,
            "note": "Pending operator approval; call the execute endpoint only after reviewing the render and metadata"}


@app.post("/api/publish/{job_id}/execute", status_code=202, dependencies=[Depends(require_api_key)])
def execute_publish(job_id: int, db: Session = Depends(get_db)):
    """Approve a queued upload; the separate worker performs the network operation."""
    job = db.get(PublishJob, job_id)
    if job is None:
        raise HTTPException(404, "Publish job not found")
    if job.status == "queued":
        return {"job_id": job.id, "status": job.status, "message": "Already queued for the worker"}
    if job.status != "pending_approval":
        raise HTTPException(409, f"Job cannot be approved from status {job.status}")
    if not settings.youtube_upload_enabled:
        raise HTTPException(503, "YouTube publishing is disabled; enable it only after OAuth verification")
    asset = db.get(Asset, job.asset_id)
    render = db.get(RenderJob, job.render_job_id)
    source = db.get(Source, asset.source_id) if asset and asset.source_id else None
    if (
        asset is None or render is None or render.asset_id != asset.id
        or render.status != "completed" or not Path(render.output_path).is_file()
    ):
        raise HTTPException(409, "The selected completed render is missing")
    if not asset.rights_verified or not source_is_publishable(source):
        raise HTTPException(403, "Current source record does not contain verified rights evidence")
    result = db.execute(
        update(PublishJob)
        .where(PublishJob.id == job.id, PublishJob.status == "pending_approval")
        .values(status="queued", approved_at=utcnow(), updated_at=utcnow())
    )
    db.commit()
    if result.rowcount != 1:
        raise HTTPException(409, "Publish job status changed; refresh before approving")
    return {
        "job_id": job.id,
        "status": "queued",
        "message": "Approved; the VyralX worker will upload it if YouTube publishing is enabled",
    }


@app.get("/api/publish", dependencies=[Depends(require_api_key)])
def list_publish_jobs(db: Session = Depends(get_db)):
    rows = db.scalars(select(PublishJob).order_by(PublishJob.id.desc()).limit(100)).all()
    return [{"id": j.id, "asset_id": j.asset_id, "render_job_id": j.render_job_id,
             "title": j.title, "privacy_status": j.privacy_status, "scheduled_at": j.scheduled_at,
             "status": j.status, "attempts": j.attempts, "youtube_video_id": j.youtube_video_id,
             "error": j.error, "created_at": j.created_at, "approved_at": j.approved_at,
             "completed_at": j.completed_at} for j in rows]


@app.post("/api/content/generate", dependencies=[Depends(require_api_key)])
def create_content_pack(payload: ContentGenerationRequest, db: Session = Depends(get_db)):
    """Generate original, editable scripts and a scene plan using the Inference gateway."""
    try:
        pack = generate_content_pack(
            payload.topic,
            video_format=payload.video_format,
            audience=payload.audience,
            tone=payload.tone,
            target_seconds=payload.target_seconds,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except Exception as exc:
        log.error("Content generation failed (error_type=%s)", type(exc).__name__)
        raise HTTPException(502, "Content generation failed; check Inference configuration and logs") from None
    record = ContentPack(
        topic=payload.topic.strip(),
        video_format=payload.video_format,
        status="generated",
        pack_json=json.dumps(pack, ensure_ascii=False),
        provider_model=str(pack.get("provider_model", ""))[:200],
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"id": record.id, "status": record.status, "content_pack": pack}


@app.get("/api/content", dependencies=[Depends(require_api_key)])
def list_content_packs(db: Session = Depends(get_db)):
    rows = db.scalars(select(ContentPack).order_by(ContentPack.id.desc()).limit(100)).all()
    return [
        {"id": row.id, "topic": row.topic, "format": row.video_format,
         "status": row.status, "provider_model": row.provider_model,
         "voiceover_status": row.voiceover_status,
         "content_pack": json.loads(row.pack_json), "created_at": row.created_at}
        for row in rows
    ]


@app.get("/api/agent/manifest", dependencies=[Depends(require_api_key)])
def agent_manifest():
    """Machine-readable VyralX capability and peer contract for FRIDAY."""
    peers = configured_peers()
    return {
        "name": "VyralX",
        "service_id": "vyralx",
        "version": app.version,
        "role": "video_discovery_production_and_youtube_distribution",
        "health_url": "/health",
        "readiness_url": "/ready",
        "authentication": {"schemes": ["Bearer", "X-API-Key"]},
        "capabilities": [
            {"id": "universe.task.execute", "method": "POST", "path": "/v1/task/execute"},
            {"id": "universe.task.status", "method": "GET", "path": "/v1/task/{task_id}"},
            {"id": "task.submit", "method": "POST", "path": "/api/v1/tasks"},
            {"id": "task.status", "method": "GET", "path": "/api/v1/tasks/{task_id}"},
            {"id": "discover.youtube", "method": "POST", "path": "/api/discover"},
            {"id": "discover.pexels", "method": "POST", "path": "/api/discover/pexels"},
            {"id": "asset.import.pexels", "method": "POST", "path": "/api/assets/import/pexels"},
            {"id": "content.generate", "method": "POST", "path": "/api/content/generate"},
            {"id": "content.voiceover", "method": "POST", "path": "/api/content/{content_id}/voiceover"},
            {"id": "project.create", "method": "POST", "path": "/api/projects"},
            {"id": "project.status", "method": "GET", "path": "/api/projects/{project_id}"},
            {"id": "project.retry", "method": "POST", "path": "/api/projects/{project_id}/retry"},
            {"id": "project.memory.sync", "method": "POST", "path": "/api/projects/{project_id}/sync-memory"},
            {"id": "project.thumbnail", "method": "GET", "path": "/api/projects/{project_id}/thumbnail"},
            {"id": "render.download", "method": "GET", "path": "/api/render/{job_id}/download"},
            {"id": "thumbnail.create", "method": "POST", "path": "/api/thumbnails"},
            {"id": "youtube.analytics.refresh", "method": "POST", "path": "/api/analytics/refresh"},
            {"id": "source.register", "method": "POST", "path": "/api/sources"},
            {"id": "asset.import", "method": "POST", "path": "/api/assets/upload"},
            {"id": "video.render", "method": "POST", "path": "/api/render", "asynchronous": True},
            {"id": "video.publish.request", "method": "POST", "path": "/api/publish"},
            {"id": "video.publish.approve", "method": "POST", "path": "/api/publish/{job_id}/execute"},
            {"id": "video.job.retry", "method": "POST", "path": "/api/jobs/{kind}/{job_id}/retry"},
            {"id": "video.publish.resolve_uncertain", "method": "POST", "path": "/api/jobs/publish/{job_id}/resolve"},
        ],
        "peer_contract": "HTTP JSON authenticated using X-API-Key; paths must be confirmed for each peer",
        "configured_peers": sorted(peers.keys()),
        "publishing_enabled": settings.youtube_upload_enabled,
        "privacy_default": settings.youtube_default_privacy,
        "rights_gate_required": True,
        "sentinel_policy_required_for_publish": settings.sentinel_required_for_publish,
    }


@app.get("/api/agents/health", dependencies=[Depends(require_api_key)])
def agent_health():
    return {
        name: peer_health(name)
        for name in ("friday", "inference", "intelx", "memora", "sentinel")
    }


@app.post("/api/jobs/render/{job_id}/retry", status_code=202, dependencies=[Depends(require_api_key)])
def retry_render_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(RenderJob, job_id)
    if job is None:
        raise HTTPException(404, "Render job not found")
    if job.status != "failed":
        raise HTTPException(409, "Only failed render jobs can be retried")
    if job.attempts >= settings.worker_max_attempts:
        raise HTTPException(409, "Retry limit reached; inspect the stored error before resetting attempts")
    db.execute(
        update(RenderJob).where(RenderJob.id == job.id, RenderJob.status == "failed")
        .values(status="queued", error="", output_path="", updated_at=utcnow(), completed_at=None)
    )
    db.commit()
    return {"job_id": job.id, "status": "queued"}


@app.post("/api/jobs/publish/{job_id}/retry", status_code=202, dependencies=[Depends(require_api_key)])
def retry_publish_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(PublishJob, job_id)
    if job is None:
        raise HTTPException(404, "Publish job not found")
    if job.status != "failed":
        raise HTTPException(409, "Only failed publish jobs can be retried")
    if job.attempts >= settings.worker_max_attempts:
        raise HTTPException(409, "Retry limit reached; inspect the stored error before resetting attempts")
    db.execute(
        update(PublishJob).where(PublishJob.id == job.id, PublishJob.status == "failed")
        .values(status="pending_approval", error="", updated_at=utcnow(),
                completed_at=None, approved_at=None)
    )
    db.commit()
    return {"job_id": job.id, "status": "pending_approval",
            "message": "Review the job and approve it again before an external upload"}


@app.post("/api/discover/pexels", dependencies=[Depends(require_api_key)])
def discover_pexels(payload: PexelsSearchRequest):
    """Search official Pexels stock footage; candidates remain unverified until import confirmation."""
    try:
        items = search_videos(
            payload.query,
            max_results=payload.max_results,
            orientation=payload.orientation,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except Exception as exc:
        log.error("Pexels discovery failed (error_type=%s)", type(exc).__name__)
        raise HTTPException(502, "Pexels discovery failed; check PEXELS_API_KEY and provider status") from None
    return {
        "provider": "Pexels",
        "query": payload.query,
        "count": len(items),
        "items": items,
        "attribution": "Credit the photographer where possible: https://www.pexels.com/",
        "license_url": "https://www.pexels.com/license/",
    }


@app.post("/api/assets/import/pexels", status_code=201, dependencies=[Depends(require_api_key)])
def import_pexels_asset(payload: PexelsImportRequest, db: Session = Depends(get_db)):
    """Import from Pexels after the operator explicitly confirms license review."""
    if not payload.confirm_license:
        raise HTTPException(
            403,
            "Review https://www.pexels.com/license/ and set confirm_license=true to import this stock clip",
        )
    destination = None
    try:
        imported = import_video_file(
            payload.video_id,
            payload.video_file_id,
            title=payload.title or f"Pexels video {payload.video_id}",
            max_bytes=min(settings.max_upload_mb, settings.max_stock_clip_mb) * 1024 * 1024,
        )
        destination = Path(imported["file_path"])
        source_url = imported["source_url"]
        source = Source(
            title=imported["title"],
            source_url=source_url,
            platform="pexels",
            creator=imported["creator"],
            license_name="Pexels Content License",
            permission_reference="https://www.pexels.com/license/",
            rights_verified=True,
            status="licensed",
            notes=(
                "Imported via official Pexels API after explicit operator confirmation of the "
                "Pexels license. Credit the creator when possible. Review provider terms for "
                "limitations before publishing."
            ),
        )
        db.add(source)
        db.flush()
        asset = Asset(
            source_id=source.id,
            title=imported["title"],
            file_path=str(destination),
            rights_verified=True,
            **imported["metadata"],
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        return {
            "asset_id": asset.id,
            "source_id": source.id,
            "title": asset.title,
            "metadata": imported["metadata"],
            "rights_verified": True,
            "creator": imported["creator"],
            "creator_url": imported["creator_url"],
            "source_url": source_url,
            "license_url": "https://www.pexels.com/license/",
            "attribution_notice": "Credit the photographer where possible.",
        }
    except ValueError as exc:
        db.rollback()
        if destination:
            destination.unlink(missing_ok=True)
        raise HTTPException(422, str(exc)) from None
    except Exception as exc:
        db.rollback()
        if destination:
            destination.unlink(missing_ok=True)
        log.error("Pexels import failed (error_type=%s)", type(exc).__name__)
        raise HTTPException(502, "Pexels import failed; check provider configuration and logs") from None

@app.post("/api/content/{content_id}/voiceover", status_code=202, dependencies=[Depends(require_api_key)])
def generate_content_voiceover(content_id: int, db: Session = Depends(get_db)):
    """Synthesize the original script through the configured Inference TTS gateway."""
    record = db.get(ContentPack, content_id)
    if record is None:
        raise HTTPException(404, "Content pack not found")
    pack = json.loads(record.pack_json)
    voiceover_text = str(pack.get("voiceover") or pack.get("script") or "").strip()
    if not voiceover_text:
        raise HTTPException(422, "Content pack contains no voiceover script")
    try:
        result = synthesize_voiceover(voiceover_text)
        record.voiceover_path = str(result["file_path"])
        record.voiceover_status = "ready"
        db.commit()
        return {
            "content_pack_id": record.id,
            "voiceover_status": record.voiceover_status,
            "bytes": result["bytes"],
            "message": "Voiceover ready; pass content_pack_id to POST /api/render",
        }
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from None
    except Exception as exc:
        db.rollback()
        record = db.get(ContentPack, content_id)
        if record is not None:
            record.voiceover_status = "failed"
            db.commit()
        log.error("Voiceover synthesis failed (error_type=%s)", type(exc).__name__)
        raise HTTPException(502, "Voiceover synthesis failed; check Inference TTS configuration and logs") from None


@app.post("/api/thumbnails", status_code=201, dependencies=[Depends(require_api_key)])
def create_thumbnail(payload: ThumbnailRequest, db: Session = Depends(get_db)):
    job = db.get(RenderJob, payload.render_job_id)
    if job is None:
        raise HTTPException(404, "Render job not found")
    if job.status != "completed" or not job.output_path or not Path(job.output_path).is_file():
        raise HTTPException(409, "Thumbnail extraction requires a completed render")
    try:
        metadata = probe_media(job.output_path)
        duration = float(metadata.get("duration_seconds") or 0)
        if duration <= 0 or payload.timestamp_seconds >= duration:
            raise HTTPException(422, "timestamp_seconds must be earlier than the rendered video duration")
        thumbnail_path = settings.render_dir / ("thumbnail-job-" + str(job.id) + ".jpg")
        extract_thumbnail(job.output_path, thumbnail_path, payload.timestamp_seconds)
    except HTTPException:
        raise
    except Exception as exc:
        log.error("Thumbnail extraction failed (error_type=%s)", type(exc).__name__)
        raise HTTPException(502, "Thumbnail extraction failed; check FFmpeg and logs") from None
    return {
        "render_job_id": job.id,
        "path": "/api/thumbnails/" + str(job.id),
        "download_name": "vyralx-thumbnail-" + str(job.id) + ".jpg",
    }


@app.get("/api/thumbnails/{job_id}", dependencies=[Depends(require_api_key)])
def get_thumbnail(job_id: int):
    path = settings.render_dir / ("thumbnail-job-" + str(job_id) + ".jpg")
    if not path.is_file():
        raise HTTPException(404, "Thumbnail not found; create it with POST /api/thumbnails")
    return FileResponse(path, media_type="image/jpeg", filename="vyralx-thumbnail-" + str(job_id) + ".jpg")


@app.post("/api/analytics/refresh", dependencies=[Depends(require_api_key)])
def refresh_analytics(db: Session = Depends(get_db)):
    """Pull view/like/comment snapshots for VyralX-published videos via YouTube Data API."""
    if not settings.youtube_analytics_enabled:
        raise HTTPException(503, "Analytics is disabled; set YOUTUBE_ANALYTICS_ENABLED=true after configuration")
    jobs = db.scalars(
        select(PublishJob).where(PublishJob.status == "uploaded", PublishJob.youtube_video_id != "")
        .order_by(PublishJob.id.desc()).limit(200)
    ).all()
    by_video = {job.youtube_video_id: job for job in jobs}
    try:
        metrics = fetch_video_metrics(list(by_video))
    except Exception as exc:
        log.error("YouTube analytics refresh failed (error_type=%s)", type(exc).__name__)
        raise HTTPException(502, "Analytics refresh failed; check YouTube Data API configuration and logs") from None
    snapshots = []
    for metric in metrics:
        job = by_video.get(metric["youtube_video_id"])
        if job is None:
            continue
        record = VideoMetric(
            publish_job_id=job.id,
            youtube_video_id=metric["youtube_video_id"],
            view_count=metric["view_count"],
            like_count=metric["like_count"],
            comment_count=metric["comment_count"],
        )
        db.add(record)
        snapshots.append({
            **metric,
            "publish_job_id": job.id,
            "engagements": metric["like_count"] + metric["comment_count"],
            "engagement_per_view": round(
                (metric["like_count"] + metric["comment_count"]) / max(1, metric["view_count"]), 6
            ),
        })
    db.commit()
    return {"snapshots_saved": len(snapshots), "items": snapshots}


@app.get("/api/analytics", dependencies=[Depends(require_api_key)])
def list_analytics(db: Session = Depends(get_db)):
    rows = db.scalars(select(VideoMetric).order_by(VideoMetric.id.desc()).limit(500)).all()
    return [
        {
            "publish_job_id": row.publish_job_id,
            "youtube_video_id": row.youtube_video_id,
            "view_count": row.view_count,
            "like_count": row.like_count,
            "comment_count": row.comment_count,
            "engagements": row.like_count + row.comment_count,
            "engagement_per_view": round(
                (row.like_count + row.comment_count) / max(1, row.view_count), 6
            ),
            "fetched_at": row.fetched_at,
        }
        for row in rows
    ]

 
@app.post("/api/jobs/publish/{job_id}/resolve", dependencies=[Depends(require_api_key)])
def resolve_uncertain_publish(
    job_id: int,
    payload: PublishResolutionRequest,
    db: Session = Depends(get_db),
):
    """Reconcile a worker crash that occurred during a remote upload."""
    job = db.get(PublishJob, job_id)
    if job is None:
        raise HTTPException(404, "Publish job not found")
    if job.status != "uncertain":
        raise HTTPException(409, "Only uncertain uploads can be resolved")
    if payload.decision == "uploaded":
        job.status = "uploaded"
        job.youtube_video_id = payload.youtube_video_id.strip()
        job.error = ""
        job.completed_at = utcnow()
        job.updated_at = utcnow()
        db.commit()
        return {
            "job_id": job.id,
            "status": job.status,
            "youtube_video_id": job.youtube_video_id,
            "message": "Upload reconciled; metrics can be refreshed later",
        }
    # The operator has confirmed the remote upload did not create a video.
    # Require another explicit approval before the worker performs a new upload.
    job.status = "pending_approval"
    job.error = ""
    job.youtube_video_id = ""
    job.approved_at = None
    job.completed_at = None
    job.updated_at = utcnow()
    db.commit()
    return {
        "job_id": job.id,
        "status": job.status,
        "message": "Reconciled as not uploaded; review and approve again to retry",
    }


def _agent_task_summary(task: AgentTask) -> dict:
    return {
        "task_id": task.task_id,
        "task_type": task.task_type,
        "correlation_id": task.correlation_id,
        "status": task.status,
        "attempts": task.attempts,
        "error": task.error,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "updated_at": task.updated_at,
        "completed_at": task.completed_at,
    }


def _friday_state(internal_state: str) -> str:
    return {
        "queued": "PENDING",
        "pending_approval": "PENDING",
        "running": "RUNNING",
        "uploading": "RUNNING",
        "completed": "SUCCESS",
        "uploaded": "SUCCESS",
        "failed": "ERROR",
        "uncertain": "DEGRADED",
        "cancelled": "CANCELLED",
    }.get(internal_state, "PENDING")


def _redact_authorization_context(value):
    """Keep useful authorization facts while never persisting credential-like values."""
    sensitive_markers = ("token", "secret", "password", "api_key", "apikey", "credential", "private_key", "cookie")
    if isinstance(value, dict):
        cleaned = {}
        for key, child in value.items():
            name = str(key)
            if any(marker in name.lower() for marker in sensitive_markers):
                cleaned[name] = "[REDACTED]"
            else:
                cleaned[name] = _redact_authorization_context(child)
        return cleaned
    if isinstance(value, list):
        return [_redact_authorization_context(item) for item in value[:100]]
    if isinstance(value, str):
        return value[:2000]
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return str(value)[:2000]


def _friday_result(task: AgentTask) -> dict:
    status = _friday_state(task.status)
    result_data = {}
    if task.result_json:
        try:
            parsed = json.loads(task.result_json)
            if isinstance(parsed, dict):
                result_data = parsed
        except ValueError:
            result_data = {}
    start = task.started_at
    end = task.completed_at or task.updated_at
    execution_time_ms = 0
    if start and end:
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        execution_time_ms = max(0, int((end - start).total_seconds() * 1000))
    receipt = None
    if status == "SUCCESS":
        receipt = {
            "requested_action": task.action or task.objective or task.task_type,
            "target": task.target_agent or "vyralx",
            "authorization_decision": "AUTHORIZED",
            "execution_timestamp": (task.completed_at or utcnow()).isoformat(),
            "result": result_data,
            "verification_evidence": {
                "evidence_type": "persisted_agent_task_result",
                "task_row_id": task.id,
                "task_type": task.task_type,
                "final_status": status,
                "completed_at": (task.completed_at or utcnow()).isoformat(),
            },
            "failure_reason": None,
        }
    summary = (
        f"VyralX completed {task.task_type}."
        if status == "SUCCESS"
        else f"VyralX task {task.task_type} is {status.lower()}."
    )
    return {
        "task_id": task.task_id,
        "target_agent": task.target_agent or "vyralx",
        "status": status,
        "final_state": status,
        "result": result_data,
        "summary": summary,
        "error": task.error or None,
        "execution_time_ms": execution_time_ms,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "receipt": receipt,
        "trace_id": task.trace_id,
        "parent_task_id": task.parent_task_id or None,
        "request_id": task.request_id or None,
        "correlation_id": task.correlation_id,
        "action": task.action,
        "objective": task.objective,
        "capability": task.capability,
        "actor": task.actor,
        "requested_mode": task.requested_mode,
        "progress": 1.0 if status in {"SUCCESS", "ERROR", "CANCELLED", "DEGRADED"} else 0.0,
    }


_TASK_ACTION_ALIASES = {
    "discover.youtube": "discover.youtube",
    "vyralx.discover.youtube": "discover.youtube",
    "youtube.discover": "discover.youtube",
    "discover.pexels": "discover.pexels",
    "vyralx.discover.pexels": "discover.pexels",
    "pexels.discover": "discover.pexels",
    "content.generate": "content.generate",
    "vyralx.content.generate": "content.generate",
    "video.content.generate": "content.generate",
    "content.voiceover": "content.voiceover",
    "vyralx.content.voiceover": "content.voiceover",
    "project.create": "project.create",
    "vyralx.project.create": "project.create",
    "video.project.create": "project.create",
    "render.create": "render.create",
    "vyralx.render.create": "render.create",
    "video.render": "render.create",
    "publish.request": "publish.request",
    "vyralx.publish.request": "publish.request",
    "youtube.publish.request": "publish.request",
}


@app.post("/v1/task/execute", status_code=202, dependencies=[Depends(require_api_key)])
def execute_friday_universe_task(
    envelope: UniverseTaskEnvelope,
    db: Session = Depends(get_db),
):
    """Implement FRIDAY's canonical POST /v1/task/execute task-envelope contract."""
    if envelope.requested_mode == "sync":
        raise HTTPException(422, "VyralX's durable task endpoint is asynchronous; use requested_mode='async' or 'background'")
    target = envelope.target_agent.strip().lower()
    if target != "vyralx":
        raise HTTPException(422, "target_agent must identify VyralX")
    candidates = [
        envelope.task_type or "",
        envelope.action,
        envelope.capability,
    ]
    resolved_type = next(
        (_TASK_ACTION_ALIASES[item.strip().lower()] for item in candidates
         if item and item.strip().lower() in _TASK_ACTION_ALIASES),
        None,
    )
    if resolved_type is None:
        raise HTTPException(
            422,
            "Unsupported VyralX task action/capability; use the allowlisted names in GET /api/agent/manifest",
        )
    task_input = envelope.inputs if envelope.inputs else envelope.payload
    if resolved_type == "project.create":
        try:
            project_request = VideoProjectCreateRequest.model_validate(task_input)
        except Exception as exc:
            from pydantic import ValidationError
            if isinstance(exc, ValidationError):
                raise HTTPException(422, detail=exc.errors()) from None
            raise
        if not project_request.confirm_pexels_license:
            raise HTTPException(403, "Review the Pexels license and explicitly confirm before queuing a video project")
        if project_request.auto_discover_trend and not settings.youtube_data_api_key:
            raise HTTPException(422, "Automatic trend discovery requires YOUTUBE_DATA_API_KEY")
    normalized_input = json.dumps(task_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    idem_key = envelope.idempotency_key.strip() if envelope.idempotency_key else f"taskid:{envelope.task_id}"
    stored_action = envelope.action or envelope.objective
    if not stored_action.strip():
        raise HTTPException(422, "action or objective must identify the requested VyralX operation")
    existing = db.scalar(select(AgentTask).where(AgentTask.task_id == envelope.task_id))
    if existing is None:
        existing = db.scalar(select(AgentTask).where(AgentTask.idempotency_key == idem_key))
    if existing is not None:
        if (
            existing.task_type != resolved_type
            or existing.input_json != normalized_input
            or existing.action != stored_action
            or existing.idempotency_key != idem_key
            or existing.target_agent != "vyralx"
        ):
            raise HTTPException(409, "task_id/idempotency_key already exists with different action, target, or input")
        return JSONResponse(
            status_code=202,
            content={
                **_friday_result(existing),
                "status_url": "/v1/task/" + existing.task_id,
                "idempotent_replay": True,
            },
        )

    trace_id = envelope.trace_id or envelope.correlation_id or envelope.task_id
    request_id = envelope.request_id or envelope.correlation_id or envelope.task_id
    authorization_context = _redact_authorization_context(envelope.authorization_context)
    task = AgentTask(
        task_id=envelope.task_id,
        idempotency_key=idem_key,
        task_type=resolved_type,
        input_json=normalized_input,
        authorization_context_json=json.dumps(authorization_context, ensure_ascii=False),
        correlation_id=envelope.correlation_id or trace_id,
        trace_id=trace_id,
        parent_task_id=envelope.parent_task_id or "",
        request_id=request_id,
        actor=envelope.actor,
        capability=envelope.capability,
        objective=envelope.objective,
        trust_level=envelope.trust_level,
        deadline=envelope.deadline or "",
        requested_mode=envelope.requested_mode,
        priority=envelope.priority,
        source_agent=envelope.source_agent,
        target_agent="vyralx",
        action=stored_action,
        status="queued",
    )
    try:
        db.add(task)
        db.commit()
        db.refresh(task)
    except Exception:
        db.rollback()
        existing = db.scalar(select(AgentTask).where(AgentTask.idempotency_key == idem_key))
        if existing is None:
            raise HTTPException(500, "Could not persist VyralX task") from None
        if (
            existing.task_type != resolved_type
            or existing.input_json != normalized_input
            or existing.action != stored_action
            or existing.idempotency_key != idem_key
            or existing.target_agent != "vyralx"
        ):
            raise HTTPException(409, "idempotency_key was concurrently reused with different action, target, or input") from None
        task = existing
    return JSONResponse(
        status_code=202,
        content={
            **_friday_result(task),
            "status_url": "/v1/task/" + task.task_id,
            "idempotent_replay": False,
        },
    )


@app.get("/v1/task/{task_id}", dependencies=[Depends(require_api_key)])
def get_friday_universe_task(task_id: str, db: Session = Depends(get_db)):
    """Return a canonical FRIDAY TaskResult with a verifiable receipt after completion."""
    task = db.scalar(select(AgentTask).where(AgentTask.task_id == task_id))
    if task is None:
        raise HTTPException(404, "VyralX task not found")
    return _friday_result(task)


@app.get("/v1/task/status/{task_id}", dependencies=[Depends(require_api_key)])
def get_friday_universe_task_status(task_id: str, db: Session = Depends(get_db)):
    """Compatibility status route for callers that separate status polling from task IDs."""
    return get_friday_universe_task(task_id, db)


@app.post("/api/v1/tasks", status_code=202, dependencies=[Depends(require_api_key)])
def submit_agent_task(payload: AgentTaskRequest, db: Session = Depends(get_db)):
    """FRIDAY-compatible durable task envelope with idempotent caller-supplied task_id."""
    normalized_input = json.dumps(payload.input, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    existing = db.scalar(select(AgentTask).where(AgentTask.task_id == payload.task_id))
    if existing is not None:
        if existing.task_type != payload.task_type or existing.input_json != normalized_input:
            raise HTTPException(409, "task_id already exists with a different task type or input")
        return {
            **_agent_task_summary(existing),
            "status_url": "/api/v1/tasks/" + existing.task_id,
            "idempotent_replay": True,
        }

    try:
        # Reject malformed task inputs before putting them in the persistent queue.
        if payload.task_type == "discover.youtube":
            DiscoveryRequest.model_validate(payload.input)
        elif payload.task_type == "discover.pexels":
            PexelsSearchRequest.model_validate(payload.input)
        elif payload.task_type == "content.generate":
            ContentGenerationRequest.model_validate(payload.input)
        elif payload.task_type == "content.voiceover":
            ContentVoiceoverRequest.model_validate(payload.input)
        elif payload.task_type == "project.create":
            VideoProjectCreateRequest.model_validate(payload.input)
        elif payload.task_type == "render.create":
            RenderRequest.model_validate(payload.input)
        elif payload.task_type == "publish.request":
            PublishRequest.model_validate(payload.input)
    except Exception as exc:
        from pydantic import ValidationError
        if isinstance(exc, ValidationError):
            raise HTTPException(422, detail=exc.errors()) from None
        raise

    task = AgentTask(
        task_id=payload.task_id,
        task_type=payload.task_type,
        input_json=normalized_input,
        correlation_id=payload.correlation_id,
        status="queued",
    )
    db.add(task)
    try:
        db.commit()
    except Exception:
        db.rollback()
        existing = db.scalar(select(AgentTask).where(AgentTask.task_id == payload.task_id))
        if existing is None:
            raise HTTPException(500, "Could not persist agent task") from None
        if existing.task_type != payload.task_type or existing.input_json != normalized_input:
            raise HTTPException(409, "task_id concurrently created with different input") from None
        task = existing
    db.refresh(task)
    return {
        **_agent_task_summary(task),
        "status_url": "/api/v1/tasks/" + task.task_id,
        "idempotent_replay": False,
    }


@app.get("/api/v1/tasks/{task_id}", dependencies=[Depends(require_api_key)])
def get_agent_task(task_id: str, db: Session = Depends(get_db)):
    task = db.scalar(select(AgentTask).where(AgentTask.task_id == task_id))
    if task is None:
        raise HTTPException(404, "Agent task not found")
    return {
        **_agent_task_summary(task),
        "result": json.loads(task.result_json or "{}") if task.result_json else {},
    }


@app.get("/api/v1/tasks", dependencies=[Depends(require_api_key)])
def list_agent_tasks(db: Session = Depends(get_db), limit: int = 50):
    limit = max(1, min(limit, 100))
    rows = db.scalars(select(AgentTask).order_by(AgentTask.id.desc()).limit(limit)).all()
    return {"count": len(rows), "items": [_agent_task_summary(task) for task in rows]}


@app.post("/api/v1/tasks/{task_id}/cancel", dependencies=[Depends(require_api_key)])
def cancel_agent_task(
    task_id: str,
    payload: AgentTaskCancelRequest,
    db: Session = Depends(get_db),
):
    task = db.scalar(select(AgentTask).where(AgentTask.task_id == task_id))
    if task is None:
        raise HTTPException(404, "Agent task not found")
    if task.status != "queued":
        raise HTTPException(409, "Only queued tasks can be cancelled")
    result = db.execute(
        update(AgentTask)
        .where(AgentTask.id == task.id, AgentTask.status == "queued")
        .values(status="cancelled", error=payload.reason, updated_at=utcnow(), completed_at=utcnow())
    )
    db.commit()
    if result.rowcount != 1:
        raise HTTPException(409, "Task state changed; refresh before cancelling")
    db.refresh(task)
    return _agent_task_summary(task)
