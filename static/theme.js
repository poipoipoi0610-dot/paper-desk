// Apply the saved appearance before styles paint. Reading state is independent.
(() => {
 const root = document.documentElement;
 const read = key => { try { return localStorage.getItem(key); } catch { return null; } };
 const write = (key, value) => { try { localStorage.setItem(key, value); } catch {} };
 const validTheme = value => value === 'light' ? 'light' : 'dark';
 const validPaper = value => ['original', 'soft'].includes(value) ? value : null;
 let theme = validTheme(read('paperDesk.theme'));
 let paper = validPaper(read('paperDesk.paperTone'));

 function apply() {
  const tone = paper || (theme === 'dark' ? 'soft' : 'original');
  root.dataset.theme = theme;
  root.dataset.paperTone = tone;
  document.querySelectorAll('[data-theme-choice]').forEach(button => {
   button.setAttribute('aria-pressed', String(button.dataset.themeChoice === theme));
  });
  const toggle = document.getElementById('paperToneBtn');
  if (toggle) {
   toggle.textContent = tone === 'soft' ? '纸张：柔和' : '纸张：原色';
   toggle.setAttribute('aria-pressed', String(tone === 'soft'));
   toggle.title = tone === 'soft' ? '恢复 PDF 原始亮度' : '降低 PDF 阅读亮度；放大图片与下载文件保持原色';
  }
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#1c1c1e' : '#ffffff');
 }
 apply();
 document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-theme-choice]').forEach(button => {
   button.addEventListener('click', () => {
    theme = validTheme(button.dataset.themeChoice);
    write('paperDesk.theme', theme);
    apply();
   });
  });
  document.getElementById('paperToneBtn')?.addEventListener('click', () => {
   paper = root.dataset.paperTone === 'soft' ? 'original' : 'soft';
   write('paperDesk.paperTone', paper);
   apply();
  });
  apply();
 });
 window.addEventListener('storage', event => {
  if (event.key === 'paperDesk.theme' || event.key === 'paperDesk.paperTone' || event.key === null) {
   theme = validTheme(read('paperDesk.theme'));
   paper = validPaper(read('paperDesk.paperTone'));
   apply();
  }
 });
})();
