"use strict";
(() => {
  let token=window.location.hash.slice(1) || sessionStorage.getItem('catalyst-local-session');
  if(window.location.hash){sessionStorage.setItem('catalyst-local-session',token);history.replaceState(null,'','/');}
  const $=selector=>document.querySelector(selector);
  let busy=false, lastModels='';
  async function request(path, body) {
    const response=await fetch(path,{method:body?'POST':'GET',headers:{Authorization:`Bearer ${token}`,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});
    const data=await response.json();if(!response.ok)throw Error(data.detail || 'Connection step failed.');return data;
  }
  function display(data) {
    $('#local-status').textContent=data.message;
    $('#local-key-step').hidden=!['awaiting-key','authenticating'].includes(data.phase);
    $('#local-model-step').hidden=!['authenticated','testing'].includes(data.phase);
    $('#local-ready-step').hidden=!['ready','working'].includes(data.phase);
    const serialized=JSON.stringify(data.models);
    if(serialized!==lastModels){$('#local-model').replaceChildren(...data.models.map(model=>new Option(model,model)));lastModels=serialized;}
    $('#local-model-name').textContent=data.actual_model || 'Model ready';
    $('#local-return').href=data.catalyst_url;
    $('#local-test-form button').disabled=data.phase==='testing';
  }
  $('#local-key-form').addEventListener('submit',async event=>{
    event.preventDefault();const form=event.currentTarget;busy=true;form.querySelector('button').disabled=true;
    const key=form.api_key.value;form.api_key.value='';
    try{display(await request('/api/key',{api_key:key}));}catch(error){$('#local-status').textContent=error.message;}
    finally{busy=false;form.querySelector('button').disabled=false;}
  });
  $('#local-test-form').addEventListener('submit',async event=>{
    event.preventDefault();const form=event.currentTarget;busy=true;form.querySelector('button').disabled=true;
    $('#local-status').textContent='Waiting for the selected model’s connection test…';
    try{display(await request('/api/test',{model:form.model.value,api_billing_accepted:form.api_billing_accepted.checked}));}catch(error){$('#local-status').textContent=error.message;}
    finally{busy=false;form.querySelector('button').disabled=false;}
  });
  $('#local-disconnect').addEventListener('click',async()=>{try{display(await request('/api/stop',{}));sessionStorage.removeItem('catalyst-local-session');}catch(error){$('#local-status').textContent=error.message;}});
  request('/api/status').then(display).catch(error=>{$('#local-status').textContent=error.message;});
  setInterval(()=>{if(!busy&&!document.hidden)request('/api/status').then(display).catch(()=>{});},3000);
})();
