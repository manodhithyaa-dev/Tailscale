
document.addEventListener("DOMContentLoaded",()=>{
 const user=JSON.parse(localStorage.getItem("nimbusUser")||'{"name":"Admin User","role":"Administrator"}');
 document.querySelectorAll(".user-avatar").forEach(a=>a.textContent=(user.name||"U").trim()[0].toUpperCase());
 document.querySelectorAll(".sidebar-user-name").forEach(e=>e.textContent=user.name||"User");
 document.querySelectorAll(".sidebar-user-role").forEach(e=>e.textContent=user.role||"Administrator");
 const role=user.role||"Administrator";
 if(role==="Viewer"){document.querySelectorAll("[data-requires-permission]").forEach(b=>{b.disabled=true;b.title="You do not have permission to perform this action.";b.style.opacity=".45"})}
 if(localStorage.getItem("nimbusTheme")==="dark")document.body.classList.add("dark");
 document.querySelectorAll(".theme-toggle-btn").forEach(b=>b.onclick=()=>{document.body.classList.toggle("dark");localStorage.setItem("nimbusTheme",document.body.classList.contains("dark")?"dark":"light")});
 const collapse=document.getElementById("sidebarCollapseBtn"); if(collapse)collapse.onclick=()=>document.querySelector(".sidebar").classList.toggle("collapsed");
 const mobile=document.getElementById("mobileNavToggle"); if(mobile)mobile.onclick=()=>document.querySelector(".sidebar").classList.toggle("mobile-open");
 document.querySelectorAll("[data-dropdown-trigger]").forEach(t=>t.onclick=(e)=>{e.stopPropagation();document.getElementById(t.dataset.dropdownTrigger).classList.toggle("show")});
 document.addEventListener("click",()=>document.querySelectorAll(".dropdown-panel").forEach(d=>d.classList.remove("show")));
 document.querySelectorAll(".logout-btn").forEach(b=>b.addEventListener("click",()=>{localStorage.removeItem("nimbusLoggedIn");location.href="login.html"}));
 renderNotifications();
});
function openModal(id){document.getElementById(id).classList.add("show")}
function closeModal(id){document.getElementById(id).classList.remove("show")}
function toast(message,type="success"){const c=document.getElementById("toastContainer");if(!c)return;const t=document.createElement("div");t.className="toast "+type;t.textContent=message;c.appendChild(t);setTimeout(()=>t.remove(),3500)}
function addNotification(message){let n=JSON.parse(localStorage.getItem("nimbusNotifications")||"[]");n.unshift({message,time:new Date().toLocaleString(),read:false});localStorage.setItem("nimbusNotifications",JSON.stringify(n.slice(0,20)));renderNotifications()}
function renderNotifications(){let n=JSON.parse(localStorage.getItem("nimbusNotifications")||"[]");const list=document.getElementById("notifList"),badge=document.getElementById("notifBadge");if(list)list.innerHTML=n.length?n.slice(0,5).map(x=>`<div class="notif-item">${x.message}<div class="notif-time">${x.time}</div></div>`).join(""):'<div class="notif-item">No notifications yet</div>';if(badge)badge.textContent=n.filter(x=>!x.read).length}
document.addEventListener("DOMContentLoaded",()=>{const b=document.getElementById("notifMarkRead");if(b)b.onclick=()=>{let n=JSON.parse(localStorage.getItem("nimbusNotifications")||"[]").map(x=>({...x,read:true}));localStorage.setItem("nimbusNotifications",JSON.stringify(n));renderNotifications()}})
