'use strict';
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.CompanionAppearance = api;
})(typeof window === 'object' ? window : globalThis, () => {
  const KEY = 'football-assistant.appearance.v1';
  const FONTS = Object.freeze({system:'-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif',sans:'"Helvetica Neue","Noto Sans CJK SC",Arial,sans-serif',serif:'"Songti SC","Noto Serif CJK SC",Georgia,serif',mono:'ui-monospace,SFMono-Regular,Consolas,monospace'});
  function normalize(value) {
    return {fontFamily:Object.hasOwn(FONTS,value?.fontFamily)?value.fontFamily:'system',fontSize:[13,14,16,18].includes(Number(value?.fontSize))?Number(value.fontSize):14,darkMode:value?.darkMode!==false};
  }
  function apply(document, value, pet = false) {
    const prefs=normalize(value), style=document.documentElement.style;
    style.setProperty('--font',FONTS[prefs.fontFamily]);style.setProperty('--base-size',`${prefs.fontSize}px`);
    if (pet) {
      style.setProperty('--bubble-font',value?.fontFamily && Object.hasOwn(FONTS,value.fontFamily)?FONTS[prefs.fontFamily]:'"851 GBai Marker",sans-serif');
      style.setProperty('--font-scale',String(prefs.fontSize/14));
    }
    document.documentElement.dataset.theme=prefs.darkMode?'dark':'light';return prefs;
  }
  function bindPet({window,document,storage,onChange=()=>{}}) {
    function render() {let value={};try {value=JSON.parse(storage.getItem(KEY)||'{}');}catch{}apply(document,value,true);onChange();}
    function changed(event) {if(event.key===KEY||event.key===null)render();}
    render();window.addEventListener('storage',changed);
    return ()=>window.removeEventListener('storage',changed);
  }
  return {KEY,FONTS,normalize,apply,bindPet};
});
