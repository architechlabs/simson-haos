import{e as d}from"./chunk.js";var s=document.createElement("template");s.innerHTML=`
  <style>
    :host { display: block; color: var(--primary-text-color); }
    .brand-lockup { display: inline-flex; padding: 8px 10px; margin-block-end: 12px; border-radius: 8px; background: #f6f5f1; }
    .brand-lockup img { display: block; width: 138px; height: auto; }
    form, label, .contact-list { display: grid; gap: 8px; }
    form { gap: 14px; }
    label, button { font: inherit; font-size: 14px; }
    select, input:not([type="checkbox"]) { font: inherit; color: inherit; background: var(--card-background-color, #fff); border: 1px solid var(--divider-color, #a9adb4); border-radius: 6px; padding: 9px 10px; min-width: 0; }
    input:focus-visible, select:focus-visible, button:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
    button { justify-self: start; min-height: 40px; padding: 6px 12px; border: 1px solid var(--divider-color, #a9adb4); border-radius: 6px; background: var(--card-background-color, #fff); color: inherit; cursor: pointer; }
    p { margin: 0; font-size: 13px; line-height: 1.5; color: var(--secondary-text-color); }
    [role="alert"] { color: var(--error-color, #b42318); }
    [hidden] { display: none !important; }
    fieldset { min-inline-size: 0; margin: 0; padding: 10px; border: 1px solid var(--divider-color, #a9adb4); border-radius: 8px; }
    legend { padding-inline: 5px; font-size: 14px; font-weight: 600; }
    .contact { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 120px), 1fr)); gap: 8px; padding-block: 8px; border-bottom: 1px solid var(--divider-color, #a9adb4); }
    .contact-actions { grid-column: 1 / -1; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; }
    .contact-actions label { display: inline-flex; align-items: center; }
    .connection-option { display: flex; align-items: center; min-block-size: 40px; cursor: pointer; }
    .connection-option input { margin: 0; flex: none; accent-color: var(--primary-color); }
    #add-contact { margin-top: 10px; }
  </style>
  <div class="brand-lockup"><img id="brand-logo" alt="Simson by Architech Labs" width="138" height="34"></div>
  <form>
    <label>Card title<input name="title" maxlength="80" autocomplete="off" placeholder="Optional"></label>
    <label>SIP realm<input name="realm" required autocomplete="off" autocapitalize="none" placeholder="office.sip.example.net"></label>
    <label>SIP WebSocket<input name="websocket" required autocomplete="off" autocapitalize="none" placeholder="wss://office.sip.example.net:7443"></label>
    <label>This screen\u2019s SIP extension<input name="extension" required inputmode="numeric" pattern="[1-9][0-9]{1,7}" autocomplete="off" placeholder="100"></label>
    <label>Carrier access prefix<input name="gateway_prefix" maxlength="7" inputmode="tel" autocomplete="off" placeholder="Optional, e.g. *859"></label>
    <label>TURN relay<input name="relay" autocomplete="off" autocapitalize="none" placeholder="Optional"></label>
    <label>Simson location ID<input name="site_id" maxlength="36" autocomplete="off" placeholder="Optional for notification links"></label>
    <div>
      <label class="connection-option"><input type="checkbox" name="keep_connected" aria-describedby="connection-help"> Keep SIP connected between dashboard views</label>
      <p id="connection-help">Registration stays active while this browser tab remains open.</p>
    </div>
    <fieldset id="media-fields" hidden>
      <legend>Home Assistant media</legend>
      <label>Camera entity<input name="camera_entity" autocomplete="off" placeholder="camera.front_door"></label>
      <label>Media player entity<input name="media_player_entity" autocomplete="off" placeholder="media_player.entry_display"></label>
      <label>Show camera during calls with<input name="media_extension" inputmode="numeric" autocomplete="off" placeholder="Doorphone extension"></label>
    </fieldset>
    <p>Use the same realm, extension, WebSocket, and relay on cards that should share a call.</p>
    <fieldset id="contacts" hidden><legend>Contacts</legend>
      <div class="contact-list"></div>
      <button type="button" id="add-contact">Add contact</button>
    </fieldset>
    <p role="alert" hidden></p>
    <button type="submit">Apply card settings</button>
  </form>`;var p=document.createElement("template");p.innerHTML=`<div class="contact">
  <label>Name<input data-field="name" maxlength="80" autocomplete="off" placeholder="Front door"></label>
  <label>Call type<select data-field="mode"><option value="extension">SIP phone</option><option value="route">Node or route</option><option value="outside">Outside</option></select></label>
  <label><span data-field="number-label">Extension</span><input data-field="extension" required inputmode="tel" maxlength="18" autocomplete="off"></label>
  <div class="contact-actions"><label><input data-field="video" type="checkbox"> Video calls</label><button type="button">Remove contact</button></div>
</div>`;var r=class extends HTMLElement{constructor(){super(),this.attachShadow({mode:"open"}).append(s.content.cloneNode(!0)),this.form=this.shadowRoot.querySelector("form"),this.contacts=this.form.querySelector(".contact-list"),this.addContact=this.form.querySelector("#add-contact"),this.addContact.addEventListener("click",()=>this.appendContact({},!0)),this.form.addEventListener("submit",t=>{t.preventDefault(),this.apply()})}set logoSrc(t){this.shadowRoot.getElementById("brand-logo").src=t}setConfig(t){this.config=t;for(let e of this.form.querySelectorAll("input[name]"))e.type==="checkbox"?e.checked=t[e.name]===!0:e.value=t[e.name]??"";let n=["custom:simson-v2-call-card","custom:simson-v2-contacts-card"].includes(t.type);if(this.form.querySelector("#media-fields").hidden=!["custom:simson-v2-call-card","custom:simson-v2-video-card","custom:simson-v2-media-card"].includes(t.type),this.form.querySelector("#contacts").hidden=!n,this.contacts.replaceChildren(),n&&Array.isArray(t.contacts))for(let e of t.contacts.slice(0,64))this.appendContact(e??{});this.addContact.disabled=this.contacts.childElementCount>=64}appendContact(t,n=!1){let e=p.content.firstElementChild.cloneNode(!0);e.querySelector('[data-field="name"]').value=t.name??"";let o=e.querySelector('[data-field="extension"]');o.value=t.extension??"";let a=e.querySelector('[data-field="mode"]'),i=e.querySelector('[data-field="video"]');a.value=t.mode??"extension",i.checked=t.video===!0;let l=()=>{e.querySelector('[data-field="number-label"]').textContent={extension:"Extension",route:"Dial code",outside:"Phone number"}[a.value],i.disabled=a.value==="outside",i.disabled&&(i.checked=!1)};a.addEventListener("change",l),l(),e.querySelector("button").addEventListener("click",()=>{let c=e.nextElementSibling??e.previousElementSibling;e.remove(),this.addContact.disabled=!1,(c?.querySelector("button")??this.addContact).focus()}),this.contacts.append(e),this.addContact.disabled=this.contacts.childElementCount>=64,n&&o.focus()}apply(){let t={...this.config};delete t.keep_connected;for(let[e,o]of new FormData(this.form)){if(e==="keep_connected"){t[e]=!0;continue}let a=o.trim();a?t[e]=a:delete t[e]}if(!this.form.querySelector("#contacts").hidden){let e=[...this.contacts.children].map(o=>{let a=o.querySelector('[data-field="extension"]').value.trim(),i=o.querySelector('[data-field="name"]').value.trim(),l=o.querySelector('[data-field="video"]').checked,c=o.querySelector('[data-field="mode"]').value;return{extension:a,...i&&{name:i},...l&&{video:l},...c!=="extension"&&{mode:c}}});e.length?t.contacts=e:delete t.contacts}let n=this.shadowRoot.querySelector('[role="alert"]');try{d(t),n.hidden=!0,this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:t},bubbles:!0,composed:!0}))}catch(e){n.textContent=e.message,n.hidden=!1}}};export{r as SimsonCardEditor};
