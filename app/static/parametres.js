/* parametres.js — zone « Paramètres » (bouton dans la barre latérale, fenêtre à onglets).
   Dépend de window.Quant (dashboard.js) et window.Reglages (reglages.js). À charger APRÈS compare.js.
   - Affichage, Score : effet immédiat (le score est recalculé par /api/scores, sans relancer l'analyse).
   - Valorisation, Analyse : modifient les calculs de chaque titre -> « Appliquer et relancer l'analyse ». */
$(function () {
  const Q = window.Quant, R = window.Reglages, T = window.Theme;
  if (!Q || !R) { console.warn('parametres.js : window.Quant ou window.Reglages est absent.'); return; }
  const { esc } = Q;
  const relanceInitiale = R.relance();
  let onglet = 'affichage', minuteur = null, enAttenteDeFin = false;

  // Ligne ~9 : Ajoute l'index 15
  const COLONNES = [[2, 'Secteur'], [3, 'Cours'], [4, 'Score'], [5, 'Profil (barres)'], [6, 'Signal'], [7, 'Marge de sécurité'],
    [8, 'Valeur estimée'], [9, 'ROIC − WACC'], [10, 'FCF yield'], [11, 'PER'], [12, 'Croissance CA 3 ans'], [13, 'Volatilité'], [14, 'Momentum 12-1'], [15, 'Mise à jour']];
  const FACTEURS = [['valo', 'Valorisation'], ['qual', 'Qualité'], ['crois', 'Croissance'], ['risq', 'Risque (sécurité)'], ['mom', 'Momentum']];
  const PROFILS = [['equilibre', 'Équilibré', [30, 25, 15, 15, 15]], ['value', 'Value', [45, 20, 10, 15, 10]], ['qualite', 'Qualité', [20, 40, 15, 15, 10]],
    ['croissance', 'Croissance', [20, 20, 35, 10, 15]], ['defensif', 'Défensif', [20, 25, 5, 40, 10]], ['momentum', 'Momentum', [15, 15, 15, 10, 45]]];
  const ONGLETS = [['affichage', 'Affichage'], ['score', 'Score'], ['valo', 'Valorisation'], ['analyse', 'Analyse'], ['donnees', 'Données']];
  const virgule = v => String(v).replace('.', ',');

  // ---------- fabrique de champs (chaque champ porte son chemin de réglage dans data-path) ----------
  const aide = t => (t ? ` title="${esc(t)}"` : '');
  const sel = (chemin, label, options, info, num) =>
    `<label class="prm-champ"${aide(info)}><span>${label}</span><select data-path="${chemin}"${num ? ' data-num="1"' : ''}>`
    + options.map(([v, t]) => `<option value="${esc(v)}"${String(R.lire(chemin)) === String(v) ? ' selected' : ''}>${esc(t)}</option>`).join('') + '</select></label>';
  const rng = (chemin, label, min, max, pas, suf, info) =>
    `<label class="prm-champ"${aide(info)}><span>${label}</span><span class="prm-rng"><input type="range" data-path="${chemin}" data-suf="${esc(suf)}" min="${min}" max="${max}" step="${pas}" value="${R.lire(chemin)}">`
    + `<output data-sortie="${chemin}">${virgule(R.lire(chemin))}${esc(suf)}</output></span></label>`;
  const num = (chemin, label, min, max, pas, info, vide) =>
    `<label class="prm-champ"${aide(info)}><span>${label}</span><input type="number" data-path="${chemin}" min="${min}" max="${max}" step="${pas}"`
    + `${vide ? ' data-nullable="1" placeholder="' + esc(vide) + '"' : ''} value="${R.lire(chemin) === null ? '' : R.lire(chemin)}"></label>`;
  const chk = (chemin, label, info) =>
    `<label class="prm-case"${aide(info)}><input type="checkbox" data-path="${chemin}"${R.lire(chemin) ? ' checked' : ''}><span>${label}</span></label>`;
  const bouton = (id, texte, extra) => `<button type="button" class="lien-bouton" id="${id}"${extra || ''}>${texte}</button>`;

  // ---------- contenu des onglets ----------
  const PANNEAUX = {
    affichage: () => `
      <label class="prm-champ"><span>Thème</span><select id="prm-theme">
        ${[['dark', 'Sombre'], ['light', 'Clair'], ['auto', 'Automatique (suit le système)']].map(([v, t]) => `<option value="${v}"${T && T.pref() === v ? ' selected' : ''}>${t}</option>`).join('')}</select></label>
      ${sel('affichage.densite', 'Densité du tableau', [['compacte', 'Compacte'], ['normale', 'Normale'], ['aeree', 'Aérée']], 'Espacement vertical des lignes')}
      ${rng('affichage.texte', 'Taille du texte', 85, 130, 5, ' %', 'Agrandit ou réduit toute l\'interface')}
      ${sel('affichage.lignes', 'Lignes par page', [25, 50, 100, 250, 500].map(n => [n, n]), 'Nombre de titres affichés avant la pagination', true)}
      ${chk('affichage.daltonien', 'Palette adaptée au daltonisme (bleu / orange au lieu de vert / rouge)', 'Ne s\'applique pas aux graphiques détaillés')}
      ${chk('affichage.resume', 'Afficher la phrase de résumé')}
      ${chk('affichage.filtres', 'Afficher le panneau de filtres')}
      <fieldset class="prm-cols"><legend>Colonnes visibles</legend>
        ${COLONNES.map(([i, nom]) => `<label class="prm-case"><input type="checkbox" data-col="${i}"${R.lire('affichage.masquees').includes(i) ? '' : ' checked'}><span>${nom}</span></label>`).join('')}
      </fieldset>
      <div class="prm-actions">${bouton('prm-reset-zone', 'Rétablir l\'affichage', ' data-zone="affichage"')}</div>`,

    score: () => `
      <p class="prm-note">Le score est un classement relatif à l'indice. Changer ces réglages recalcule le classement tout de suite, sans relancer l'analyse.</p>
      <div class="prm-presets"><span>Profils :</span>${PROFILS.map(([id, nom]) => bouton('', nom, ` data-profil="${id}"`).replace(' id=""', '')).join('')}</div>
      ${FACTEURS.map(([k, nom]) => `<label class="prm-champ"><span>${nom}</span><span class="prm-rng"><input type="range" data-path="score.poids.${k}" min="0" max="100" step="5" value="${R.lire('score.poids.' + k)}">`
        + `<output data-poids="${k}"></output></span></label>`).join('')}
      <p class="prm-note" id="prm-total"></p>
      ${rng('score.poids_secteur', 'Poids de la comparaison sectorielle', 0, 100, 5, ' %', '100 % = comparé uniquement aux titres du même secteur ; 0 % = à tout l\'indice')}
      <div class="prm-grille">
        ${num('score.achat_fort', 'Achat fort : score ≥', 50, 100, 1, 'Seuil du signal ACHAT FORT (exige aussi une bonne valorisation et un risque maîtrisé)')}
        ${num('score.achat', 'Achat : score ≥', 50, 99, 1, 'Seuil du signal ACHAT')}
        ${num('score.vente', 'Vente : score ≤', 1, 60, 1, 'Seuil du signal VENTE')}
        ${num('score.couverture_min', 'Données minimales (%)', 0, 100, 5, 'En dessous, le signal est INSUFFISANT')}
      </div>
      ${chk('score.exclure_fin', 'Exclure les banques et assurances du tableau et du classement', 'Leurs métriques (FCF, dette nette…) ne se comparent pas aux autres secteurs')}
      <div class="prm-actions">${bouton('prm-reset-zone', 'Rétablir le score', ' data-zone="score"')}</div>`,

    valo: () => `
      <p class="prm-note">Ces hypothèses changent le coût du capital, le DCF et la marge de sécurité de chaque titre : elles demandent de relancer l'analyse. Les résultats obtenus avec d'autres hypothèses sont conservés à part.</p>
      ${rng('valo.erp', 'Prime de risque actions', 3, 9, 0.1, ' %', 'Rendement supplémentaire exigé pour détenir des actions plutôt que le taux sans risque (CAPM)')}
      ${rng('valo.g_term', 'Croissance à long terme (plafond)', 0, 4, 0.1, ' %', 'Croissance perpétuelle du DCF ; limitée aussi à (taux sans risque − 0,5 %)')}
      ${num('valo.rf', 'Taux sans risque manuel (%)', 0, 15, 0.05, 'Vide = 10 ans américain mesuré automatiquement', 'automatique')}
      ${rng('valo.ecart_g', 'Écart de croissance des scénarios', 0.5, 8, 0.5, ' pts', 'Scénario prudent : croissance − écart ; optimiste : croissance + écart')}
      ${rng('valo.ecart_ke', 'Écart de coût des fonds propres', 0.25, 4, 0.25, ' pts', 'Scénario prudent : coût + écart ; optimiste : coût − écart')}
      <div class="prm-actions">${bouton('prm-reset-zone', 'Rétablir les hypothèses', ' data-zone="valo"')}</div>`,

    analyse: () => `
      ${rng('analyse.concurrence', 'Titres analysés en parallèle', 1, 10, 1, '', 'Plus haut = plus rapide, mais Yahoo risque de limiter les requêtes (erreur 429)')}
      <p class="prm-note">Si l'analyse affiche beaucoup de titres « sans données », baissez cette valeur à 2 ou 3 et videz le cache.</p>
      <div class="prm-actions">${bouton('prm-cache', 'Vider le cache et relancer')}${bouton('prm-reset-zone', 'Rétablir l\'analyse', ' data-zone="analyse"')}</div>`,

    donnees: () => `
      <p class="prm-note">Les réglages sont enregistrés dans ce navigateur. Exportez-les pour les sauvegarder ou les reprendre ailleurs.</p>
      <div class="prm-actions">${bouton('prm-export', 'Exporter les réglages')}
        <label class="lien-bouton prm-fichier">Importer…<input type="file" id="prm-import" accept=".json,application/json" hidden></label></div>
      <div class="prm-actions">${bouton('prm-favoris', 'Effacer mes favoris')}${bouton('prm-reset-tout', 'Tout rétablir')}</div>`
  };

  // ---------- fenêtre ----------
  const dlg = document.createElement('dialog');
  dlg.id = 'prm-dlg';
  document.body.appendChild(dlg);
  dlg.addEventListener('click', e => { if (e.target === dlg) dlg.close(); });

  function rendre() {
    dlg.innerHTML = `<div class="prm-in"><form method="dialog" class="cmp-fermer"><button aria-label="Fermer">×</button></form><h2>Paramètres</h2>`
      + `<div class="prm-onglets" role="tablist">${ONGLETS.map(([id, t]) => `<button type="button" role="tab" data-onglet="${id}" aria-selected="${id === onglet}">${t}</button>`).join('')}</div>`
      + `<div class="prm-corps" role="tabpanel">${PANNEAUX[onglet]()}</div>`
      + `<div class="prm-pied"><span id="prm-msg" role="status"></span><span id="prm-attente" hidden>Réglages modifiés : relancez pour les appliquer.</span>`
      + `<button type="button" class="bouton" id="prm-relancer" hidden>Appliquer et relancer l'analyse</button></div></div>`;
    majPoids(); majPied();
  }
  const message = m => { const el = dlg.querySelector('#prm-msg'); if (el) el.textContent = m; };

  function majPoids() {
    const total = FACTEURS.reduce((s, [k]) => s + R.lire('score.poids.' + k), 0);
    FACTEURS.forEach(([k]) => {
      const o = dlg.querySelector(`output[data-poids="${k}"]`);
      if (o) o.textContent = total > 0 ? Math.round(R.lire('score.poids.' + k) / total * 100) + ' %' : '–';
    });
    const t = dlg.querySelector('#prm-total');
    if (t) t.textContent = total > 0 ? 'Les pondérations sont ramenées à 100 % : seules leurs proportions comptent.' : 'Toutes les pondérations sont à zéro : les valeurs par défaut s\'appliquent.';
  }
  function majPied() {
    const attente = R.relance() !== relanceInitiale;
    const a = dlg.querySelector('#prm-attente'), b = dlg.querySelector('#prm-relancer');
    if (a) a.hidden = !attente;
    if (b) b.hidden = !attente;
    const n = R.modifies() + (T && T.pref() !== 'dark' ? 1 : 0);
    $('#prm-resume-rail').text(n ? `${n} réglage${n > 1 ? 's' : ''} modifié${n > 1 ? 's' : ''}` : 'Réglages par défaut');
  }

  // ---------- application des réglages ----------
  function appliquerAffichage() {
    const A = R.get().affichage;
    R.appliquerVisuel();
    Q.table.page.len(A.lignes);
    COLONNES.forEach(([i]) => Q.table.column(i).visible(!A.masquees.includes(i), false));
    Q.table.columns.adjust().draw(false);
    $('#resume').toggle(A.resume);
    $('.filtres').toggle(A.filtres);
  }

  // « Exclure les financières » : masque aussi les lignes (le classement, lui, est recalculé sans elles)
  $.fn.dataTable.ext.search.push(function (settings, data, idx) {
    if (settings.nTable.id !== 'tbl' || !R.lire('score.exclure_fin')) return true;
    const r = Q.table.row(idx).data();
    return !(r && r.est_fin);
  });

  function planifierRescore() { clearTimeout(minuteur); minuteur = setTimeout(rescorer, 350); }
  async function rescorer() {
    if (Q.src && Q.src.readyState !== 2) { enAttenteDeFin = true; message('Le classement sera recalculé à la fin de l\'analyse.'); return; }
    const exclure = R.lire('score.exclure_fin');
    const lignes = Object.values(Q.donnees).filter(r => !(exclure && r.est_fin)).map(r => { const c = Object.assign({}, r); delete c.resume; delete c.url; return c; });
    if (!lignes.length) { Q.table.draw(false); return; }
    message('Recalcul du classement…');
    try {
      const rep = await fetch('/api/scores', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ lignes, reglages: R.serveur() }) });
      if (!rep.ok) throw new Error('serveur ' + rep.status);
      const sc = await rep.json();
      Q.table.rows().every(function () { const d = this.data(); if (sc[d.ticker]) { Object.assign(d, sc[d.ticker]); this.data(d); } });
      Q.table.draw(false);
      if (Q.majResume) Q.majResume();
      message(`Classement mis à jour (${lignes.length} titres).`);
    } catch (e) { message('Recalcul impossible : ' + e.message); }
  }
  if (Q.src) Q.src.addEventListener('close', () => { if (enAttenteDeFin) { enAttenteDeFin = false; rescorer(); } });

  function reagir(chemin) {
    const zone = String(chemin).split('.')[0];
    if (zone === 'affichage') appliquerAffichage();
    if (zone === 'score') { majPoids(); planifierRescore(); }
    majPied();
  }

  // ---------- événements ----------
  function changer(el) {
    let v;
    if (el.type === 'checkbox') v = el.checked;
    else if (el.type === 'range' || el.type === 'number') {
      v = el.value === '' ? null : parseFloat(el.value);
      if (v === null && !el.dataset.nullable) return;
      if (v !== null && !Number.isFinite(v)) return;
    } else v = el.dataset.num ? parseFloat(el.value) : el.value;
    R.set(el.dataset.path, v);
    const o = dlg.querySelector(`output[data-sortie="${el.dataset.path}"]`);
    if (o) o.textContent = virgule(v) + (el.dataset.suf || '');
    reagir(el.dataset.path);
  }
  $(dlg).on('input', 'input[type=range][data-path]', function () { changer(this); });
  $(dlg).on('change', '[data-path]:not([type=range])', function () { changer(this); });
  $(dlg).on('change', '#prm-theme', function () { if (T) T.set(this.value); majPied(); });
  $(dlg).on('change', 'input[data-col]', function () {
    const masquees = COLONNES.map(([i]) => i).filter(i => !dlg.querySelector(`input[data-col="${i}"]`).checked);
    R.set('affichage.masquees', masquees); reagir('affichage.masquees');
  });
  $(dlg).on('click', '[data-onglet]', function () { onglet = this.dataset.onglet; rendre(); });
  $(dlg).on('click', '[data-profil]', function () {
    const p = PROFILS.find(x => x[0] === this.dataset.profil);
    FACTEURS.forEach(([k], i) => { R.set('score.poids.' + k, p[2][i]); const el = dlg.querySelector(`input[data-path="score.poids.${k}"]`); if (el) el.value = p[2][i]; });
    reagir('score.poids');
  });
  $(dlg).on('click', '#prm-reset-zone', function () {
    R.reinitialiser(this.dataset.zone); rendre(); reagir(this.dataset.zone);
  });
  $(dlg).on('click', '#prm-relancer', () => location.reload());
  $(dlg).on('click', '#prm-cache', async function () {
    message('Vidage du cache…');
    try {
      const rep = await fetch('/api/cache/vider', { method: 'POST' });
      const d = await rep.json();
      message(`${d.supprimes} analyses supprimées, rechargement…`);
      setTimeout(() => location.reload(), 700);
    } catch (e) { message('Impossible de vider le cache : ' + e.message); }
  });
  $(dlg).on('click', '#prm-export', function () {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([R.exporter()], { type: 'application/json' }));
    a.download = 'reglages-terminal.json';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });
  $(dlg).on('change', '#prm-import', function () {
    const f = this.files && this.files[0];
    if (!f) return;
    const lecteur = new FileReader();
    lecteur.onload = () => { if (R.importer(String(lecteur.result))) location.reload(); else message('Fichier de réglages invalide.'); };
    lecteur.readAsText(f);
  });
  $(dlg).on('click', '#prm-favoris', function () {
    if (!confirm('Effacer tous les favoris ?')) return;
    try { localStorage.removeItem('quant_favoris'); } catch (e) { /* stockage indisponible */ }
    location.reload();
  });
  $(dlg).on('click', '#prm-reset-tout', function () {
    if (!confirm('Rétablir tous les réglages (y compris le thème) ?')) return;
    R.reinitialiser(); if (T) T.set('dark'); location.reload();
  });

  // ---------- bouton dans la barre latérale ----------
  $('#parametres').html('<button type="button" class="lien-bouton" id="prm-ouvrir">⚙ Ouvrir les réglages</button><p class="prm-resume" id="prm-resume-rail"></p>');
  $('#prm-ouvrir').on('click', () => { rendre(); if (!dlg.open) dlg.showModal(); });

  appliquerAffichage();     // réglages d'affichage enregistrés (colonnes, lignes par page, textes masqués)
  majPied();
  Q.parametres = { ouvrir: () => $('#prm-ouvrir').trigger('click'), rescorer };
});
