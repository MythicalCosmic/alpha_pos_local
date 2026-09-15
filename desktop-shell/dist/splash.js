// Status updates are pushed from the shell with WebviewWindow::eval.
window.setStatus = function (text, progress) {
  var status = document.getElementById('status');
  var bar = document.getElementById('progress');
  if (status && typeof text === 'string') status.textContent = text;
  if (bar && typeof progress === 'number') bar.style.width = Math.max(0, Math.min(100, progress)) + '%';
};
