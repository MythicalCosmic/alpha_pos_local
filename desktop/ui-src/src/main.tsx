import './styles/tokens.css';
import './styles/base.css';
import './styles/components.css';
import { render } from 'preact';
import { App } from './app/App';
import en from './i18n/en';
import { loadDict, type Dict } from './i18n';
import { applyDocumentPrefs, readCachedPrefs } from './lib/prefs';
import { router } from './router/router';
import { preloadPage } from './router/routes';

const prefs = readCachedPrefs();
applyDocumentPrefs(prefs);
const initial = router().getState().route;
// Start the first page chunk in parallel with the locale.
const firstPage = preloadPage(initial).catch(() => undefined);

let dict: Dict = en;
if (prefs.lang !== 'en') {
  try {
    dict = await loadDict(prefs.lang);
  } catch {
    dict = en;
  }
}
await firstPage;

render(<App initialPrefs={prefs} initialDict={dict} />, document.getElementById('root')!);
