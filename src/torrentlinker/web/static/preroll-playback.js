"use strict";
let preRollYT;
function preRollYouTube(){if(window.YT?.Player)return Promise.resolve(window.YT);if(!preRollYT)preRollYT=new Promise((resolve,reject)=>{const timeout=setTimeout(()=>reject(Error("YouTube unavailable")),15000);window.onYouTubeIframeAPIReady=()=>{clearTimeout(timeout);resolve(window.YT)};const script=document.createElement("script");script.src="https://www.youtube.com/iframe_api";script.onerror=()=>{clearTimeout(timeout);reject(Error("YouTube unavailable"))};document.head.append(script)});return preRollYT}
async function playPrerolls(plan,current=()=>true){
 if(!plan.steps?.length||!current())return;
 const dialog=element("dialog");dialog.className="preroll-playback";const heading=element("h2",say("Before your film","Avant votre film")),progress=element("p"),stage=element("div"),actions=element("div");dialog.append(heading,progress,stage,actions);document.body.append(dialog);dialog.showModal();
 let stopped=false,advance=()=>{},cleanup=()=>{};const skip=button(say("Skip clip","Passer le clip"),()=>advance()),all=button(say("Skip all · start film","Tout passer · lancer le film"),()=>{stopped=true;advance()});actions.append(skip,all);dialog.addEventListener("cancel",e=>{e.preventDefault();stopped=true;advance()});
 const monitor=setInterval(()=>{if(!current()){stopped=true;advance()}},100);
 try{for(const[index,step]of plan.steps.entries()){
  if(stopped||!current())break;stage.replaceChildren();progress.textContent=`${index+1} / ${plan.steps.length} · ${step.title}`;
  await new Promise(resolve=>{let done=false,timer=0,player=null;advance=()=>{if(done)return;done=true;clearTimeout(timer);cleanup();resolve()};cleanup=()=>{if(player?.destroy)player.destroy();if(player?.pause){player.pause();player.removeAttribute("src");player.load()}cleanup=()=>{}};
   if(step.kind==="pause"){stage.append(element("p",say("Intermission","Pause")));timer=setTimeout(advance,Math.min(60,step.seconds)*1000);return}
   if(step.kind==="youtube"){
    const mount=element("div");stage.append(mount);preRollYouTube().then(YT=>{if(done||stopped)return;const iframe=element("iframe");iframe.referrerPolicy="strict-origin-when-cross-origin";iframe.allow="autoplay; encrypted-media; fullscreen";iframe.src=`https://www.youtube-nocookie.com/embed/${encodeURIComponent(step.youtube)}?enablejsapi=1&autoplay=1&playsinline=1&origin=${encodeURIComponent(location.origin)}`;mount.replaceWith(iframe);player=new YT.Player(iframe,{host:"https://www.youtube-nocookie.com",videoId:step.youtube,playerVars:{autoplay:1,playsinline:1,origin:location.origin},events:{onReady:event=>{const iframe=event.target.getIframe();iframe.referrerPolicy="strict-origin-when-cross-origin";clearTimeout(timer);timer=setTimeout(advance,610000)},onStateChange:event=>{if(event.data===0)advance()},onError:advance}})}).catch(advance);timer=setTimeout(advance,20000);return
   }
   const video=element("video");player=video;video.controls=true;video.playsInline=true;video.src=step.url;video.onended=advance;video.onerror=advance;video.onplaying=()=>{clearTimeout(timer);timer=setTimeout(advance,610000)};stage.append(video);timer=setTimeout(advance,30000);video.play().catch(()=>{clearTimeout(timer);stage.append(element("p",say("Press Play or skip this clip.","Appuyez sur Lecture ou passez ce clip.")))})
  });cleanup();
 }}finally{clearInterval(monitor);cleanup();dialog.close();dialog.remove()}
}
async function previewPreroll(id){const data=await api("prerolls"),clip=data.clips.find(c=>c.id===id);if(!clip)throw Error("Clip unavailable");return playPrerolls({steps:[{kind:clip.source==="youtube"?"youtube":"clip",title:clip.title,youtube:clip.youtube,url:`api/prerolls/clips/${encodeURIComponent(id)}`} ]})}
