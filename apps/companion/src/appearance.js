'use strict';
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.CompanionAppearance = api;
})(typeof window === 'object' ? window : globalThis, () => {
  const KEY = 'football-assistant.appearance.v1';
  const FONTS = Object.freeze({system:'-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif',sans:'"Helvetica Neue","Noto Sans CJK SC",Arial,sans-serif',serif:'"Songti SC","Noto Serif CJK SC",Georgia,serif',mono:'ui-monospace,SFMono-Regular,Consolas,monospace'});
  const knownFont = value => typeof value === 'string' && Object.hasOwn(FONTS,value);
  const numeric = value => typeof value === 'number' || typeof value === 'string' ? Number(value) : NaN;
  function normalize(value) {
    const fontSize=numeric(value?.fontSize), seconds=numeric(value?.bubbleDurationSeconds);
    return {fontFamily:knownFont(value?.fontFamily)?value.fontFamily:'system',fontSize:[13,14,16,18].includes(fontSize)?fontSize:14,darkMode:value?.darkMode!==false,lightMotion:value?.lightMotion!==false,bubbleDurationMode:value?.bubbleDurationMode==='fixed'?'fixed':'auto',bubbleDurationSeconds:Number.isInteger(seconds)&&seconds>=2&&seconds<=60?seconds:8};
  }
  function apply(document, value, pet = false) {
    const prefs=normalize(value), style=document.documentElement.style;
    style.setProperty('--font',FONTS[prefs.fontFamily]);style.setProperty('--base-size',`${prefs.fontSize}px`);
    if (pet) {
      style.setProperty('--bubble-font',knownFont(value?.fontFamily)?FONTS[prefs.fontFamily]:'"851 GBai Marker",sans-serif');
      style.setProperty('--font-scale',String(prefs.fontSize/14));
      style.setProperty('--bubble-font-size',`${prefs.fontSize}px`);
    }
    document.documentElement.dataset.theme=prefs.darkMode?'dark':'light';return prefs;
  }
  function bindPet({window,document,storage,onChange=()=>{}}) {
    function render() {let value={};try {value=JSON.parse(storage.getItem(KEY)||'{}');}catch{}const prefs=apply(document,value,true);onChange(prefs);}
    function changed(event) {if(event.key===KEY||event.key===null)render();}
    render();window.addEventListener('storage',changed);
    return ()=>window.removeEventListener('storage',changed);
  }
  return {KEY,FONTS,normalize,apply,bindPet};
});
