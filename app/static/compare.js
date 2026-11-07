/* compare.js — comparateur « VS ».
   À charger APRÈS dashboard.js, qui doit exposer window.Quant = { donnees, table, esc, fmt, vide, SECTEURS_FR }.
   Deux façons d'ajouter un titre : le bouton ⇄ d'une ligne du tableau, ou le bouton « Comparer deux titres »
   (saisie d'un ticker, y compris hors de l'indice analysé : chargé à la demande via /api/titre/<ticker>). */
$(function () {
  const Q = window.Quant;
  if (!Q) { console.warn('compare.js : window.Quant est absent (voir l\'ajout à la fin de dashboard.js).'); return; }
  const { donnees, esc, fmt, vide, SECTEURS_FR } = Q;
  const ND = '<span class="nd">–</span>';

  const slots = [null, null];        // tickers choisis (A, B)
  Q.cmpSel = slots;                  // lu par dashboard.js pour afficher l'état des boutons ⇄
  const externes = {};               // lignes chargées hors du scan en cours
  const ligneDe = tk => (tk && (donnees[tk] || externes[tk])) || null;
  const dansScan = tk => !!(tk && donnees[tk]);

  // ---------- critères comparés : s = sens (+1 plus haut = mieux, −1 plus bas = mieux) ----------
  const ZONE = { 'sûre': 2, 'grise': 1, 'détresse': 0 };
  const GROUPES = [
    { nom: 'Notation relative', note: true, lignes: [
      { l: 'Score', v: 'score', s: 1, d: 0, u: '' }, { l: 'Valorisation', v: 'valo', s: 1, d: 0, u: '' },
      { l: 'Qualité', v: 'qual', s: 1, d: 0, u: '' }, { l: 'Croissance', v: 'crois', s: 1, d: 0, u: '' },
      { l: 'Risque (haut = plus sûr)', v: 'risq', s: 1, d: 0, u: '' }, { l: 'Momentum', v: 'mom', s: 1, d: 0, u: '' } ] },
    { nom: 'Valorisation', lignes: [
      { l: 'Marge de sécurité', v: 'marge_secu', s: 1, d: 1, u: ' %' }, { l: 'PER', v: 'per', s: -1, d: 1, u: '' },
      { l: 'EV / EBITDA', v: 'ev_ebitda', s: -1, d: 1, u: ' x' }, { l: 'FCF yield', v: 'fcf_yield', s: 1, d: 1, u: ' %' },
      { l: 'Rendement du dividende', v: 'div_yield', s: 1, d: 2, u: ' %' } ] },
    { nom: 'Rentabilité', lignes: [
      { l: 'ROIC', v: 'roic', s: 1, d: 1, u: ' %' }, { l: 'ROIC − WACC', v: 'spread', s: 1, d: 1, u: ' pts' },
      { l: 'Marge opérationnelle', v: 'marge_op', s: 1, d: 1, u: ' %' }, { l: 'ROE', v: 'roe', s: 1, d: 1, u: ' %' } ] },
    { nom: 'Solidité', lignes: [
      { l: 'Dette nette / EBITDA', v: 'nd_ebitda', s: -1, d: 1, u: ' x' }, { l: 'Dette / fonds propres', v: 'de', s: -1, d: 0, u: ' %' },
      { l: 'Altman (zone)', v: r => ZONE[r.altman_zone] ?? null, s: 1, d: 0, u: '', t: r => r.altman_zone ? esc(r.altman_zone) : ND },
      { l: 'Piotroski (sur 9)', v: r => r.piotroski_n ? r.piotroski / r.piotroski_n * 9 : null, s: 1, d: 1, u: '' } ] },
    { nom: 'Croissance', lignes: [
      { l: 'Chiffre d\'affaires (3 ans)', v: 'cagr_ca', s: 1, d: 1, u: ' %' }, { l: 'Free cash-flow (3 ans)', v: 'cagr_fcf', s: 1, d: 1, u: ' %' } ] },
    { nom: 'Risque et tendance', lignes: [
      { l: 'Volatilité (1 an)', v: 'vol', s: -1, d: 1, u: ' %' }, { l: 'Baisse maximale (1 an)', v: 'mdd', s: 1, d: 1, u: ' %' },
      { l: 'Sharpe', v: 'sharpe', s: 1, d: 2, u: '' }, { l: 'Momentum 12-1', v: 'mom_12_1', s: 1, d: 1, u: ' %' } ] },
  ];
  const val = (s, r) => (typeof s.v === 'function' ? s.v(r) : r[s.v]);
  const texte = (s, r) => { const v = val(s, r); return vide(v) ? ND : (s.t ? s.t(r) : fmt(v, s.d, s.u)); };

  // égalité pratique : écart < 0,05 ou < 2 % : évite de désigner un « gagnant » sur du bruit
  function gagnant(va, vb, sens) {
    if (vide(va) || vide(vb)) return 0;
    const ecart = Math.abs(va - vb), ref = Math.max(Math.abs(va), Math.abs(vb), 1e-9);
    if (ecart < 0.05 || ecart / ref < 0.02) return 0;
    return (va - vb) * sens > 0 ? 1 : -1;
  }

  function calculer(a, b, avecNotation) {
    let na = 0, nb = 0, egal = 0;
    const groupes = GROUPES.filter(g => !g.note || avecNotation).map(g => {
      let ga = 0, gb = 0;
      const lignes = g.lignes.map(s => {
        const va = val(s, a), vb = val(s, b), w = gagnant(va, vb, s.s);
        if (w > 0) ga++; else if (w < 0) gb++; else if (!vide(va) && !vide(vb)) egal++;
        return { s, w };
      });
      if (!g.note) { na += ga; nb += gb; }      // la notation est dérivée des autres critères : pas comptée deux fois
      return { g, lignes, ga, gb };
    });
    return { groupes, na, nb, egal };
  }

  // ---------- fenêtre ----------
  const dlg = document.createElement('dialog');
  dlg.id = 'cmp-dlg';
  document.body.appendChild(dlg);
  dlg.addEventListener('click', e => { if (e.target === dlg) dlg.close(); });   // clic sur le fond = fermer
  const liste = $('<datalist id="cmp-list"></datalist>').appendTo('body');

  function tete(i, r) {
    return `<div class="cmp-tete"><label>Titre ${'AB'[i]}
        <input list="cmp-list" data-i="${i}" value="${esc(slots[i] || '')}" placeholder="ex. ${i ? 'XOM' : 'TTE.PA'}" autocomplete="off" spellcheck="false"></label>`
      + (r ? `<strong>${esc(r.nom)}</strong><small>${esc(SECTEURS_FR[r.secteur] || r.secteur)} · ${fmt(r.prix, 2)} ${esc(r.devise)}</small>` : '')
      + '</div>';
  }

  function corps(a, b) {
    const avecNotation = dansScan(a.ticker) && dansScan(b.ticker);
    const { groupes, na, nb, egal } = calculer(a, b, avecNotation);
    const A = esc(a.ticker), B = esc(b.ticker);
    const puces = groupes.filter(x => !x.g.note).map(({ g, ga, gb }) => {
      const qui = ga === gb ? 'égalité' : (ga > gb ? A : B);
      return `<span class="cmp-puce ${ga === gb ? '' : (ga > gb ? 'a' : 'b')}">${esc(g.nom)} : <strong>${qui}</strong></span>`;
    }).join('');
    const avert = [];
    if (a.secteur !== b.secteur) avert.push('Secteurs différents : PER, EV/EBITDA, ROIC et endettement ne se comparent pas directement d\'un secteur à l\'autre.');
    if (a.devise !== b.devise) avert.push(`Devises différentes (${esc(a.devise)} / ${esc(b.devise)}) : seuls les ratios sont comparables, pas les cours.`);
    if (!avecNotation) avert.push('Notation relative indisponible : au moins un titre n\'appartient pas à l\'indice analysé (le score est un classement dans cet indice).');
    [a, b].forEach(r => (r.alertes || []).concat(r.alertes_score || []).forEach(m => avert.push(`${esc(r.ticker)} : ${esc(m)}`)));

    let html = `<div class="cmp-verdict"><p><strong>${A}</strong> l'emporte sur <strong>${na}</strong> critères, <strong>${B}</strong> sur <strong>${nb}</strong>`
      + `${egal ? `, ${egal} à égalité` : ''}.</p><div class="cmp-puces">${puces}</div>`
      + `<p class="cmp-note">Décompte simple, non pondéré : tous les critères ne pèsent pas autant. Ce n'est pas un conseil en investissement.</p></div>`;
    html += `<table class="cmp-table"><thead><tr><th></th><th>${A}</th><th>${B}</th></tr></thead><tbody>`;
    groupes.forEach(({ g, lignes }) => {
      html += `<tr class="cmp-g"><th colspan="3">${esc(g.nom)}</th></tr>`;
      lignes.forEach(({ s, w }) => {
        html += `<tr><th scope="row">${esc(s.l)}</th><td class="${w > 0 ? 'gagne' : ''}">${texte(s, a)}</td><td class="${w < 0 ? 'gagne' : ''}">${texte(s, b)}</td></tr>`;
      });
    });
    html += '</tbody></table>';
    if (avert.length) html += '<ul class="alertes">' + avert.map(m => `<li>${m}</li>`).join('') + '</ul>';
    return html;
  }

  function rendre() {
    const a = ligneDe(slots[0]), b = ligneDe(slots[1]);
    dlg.innerHTML = `<div class="cmp-in"><form method="dialog" class="cmp-fermer"><button aria-label="Fermer">×</button></form>`
      + `<h2>Comparer deux titres</h2><div class="cmp-tetes">${tete(0, a)}${tete(1, b)}</div><p class="cmp-msg" role="status"></p>`
      + (a && b ? corps(a, b)
        : '<p class="cmp-vide">Choisissez deux titres : tapez un ticker ou prenez-en un dans la liste. Un titre hors de cet indice est chargé à la demande.</p>')
      + '</div>';
  }
  const message = m => $(dlg).find('.cmp-msg').text(m);

  function ouvrir() {
    liste.html(Object.values(donnees).map(r => `<option value="${esc(r.ticker)}">${esc(r.nom)}</option>`).join(''));
    rendre();
    if (!dlg.open) dlg.showModal();
  }

  async function choisir(i, saisie) {
    const tk = String(saisie || '').trim().toUpperCase().split(/\s+/)[0];
    if (!tk) { slots[i] = null; rendre(); majTray(); return; }
    if (!ligneDe(tk)) {
      message(`Chargement de ${tk}…`);
      try {
        const rep = await fetch('/api/titre/' + encodeURIComponent(tk));
        if (!rep.ok) throw new Error(((await rep.json().catch(() => ({}))).detail) || 'Titre introuvable');
        externes[tk] = await rep.json();
      } catch (e) { message(`${tk} : ${e.message}`); return; }
    }
    slots[i] = tk; rendre(); majTray();
  }
  $(dlg).on('change', 'input[data-i]', function () { choisir(+this.dataset.i, this.value); });

  // ---------- bandeau « sélection en cours » ----------
  const tray = $('<div id="cmp-tray" hidden role="region" aria-label="Comparateur"></div>').appendTo('body');
  function majTray() {
    $('#tbl button.cmp').each(function () { $(this).toggleClass('actif', slots.includes(this.dataset.ticker)); });
    if (!slots.some(Boolean)) { tray.prop('hidden', true); return; }
    tray.html(`<span>Comparer</span> <strong>${esc(slots[0] || '…')}</strong> <span>vs</span> <strong>${esc(slots[1] || '…')}</strong>`
      + '<button type="button" id="cmp-go" class="bouton">Ouvrir</button><button type="button" id="cmp-clear" class="lien-bouton">Vider</button>').prop('hidden', false);
  }
  tray.on('click', '#cmp-go', ouvrir);
  tray.on('click', '#cmp-clear', () => { slots[0] = slots[1] = null; majTray(); });

  // bouton ⇄ d'une ligne du tableau : remplit le premier emplacement libre (sinon remplace A puis B)
  $('#tbl tbody').on('click', 'button.cmp', function (e) {
    e.stopPropagation();
    const tk = this.dataset.ticker, i = slots.indexOf(tk);
    if (i >= 0) slots[i] = null;
    else { const libre = slots.indexOf(null); if (libre >= 0) slots[libre] = tk; else { slots[0] = slots[1]; slots[1] = tk; } }
    majTray();
  });

  // point d'entrée toujours visible, à côté des filtres prédéfinis
  $('<button type="button" id="cmp-open" class="lien-bouton">⇄ Comparer deux titres</button>').appendTo('.presets').on('click', ouvrir);

  Q.cmp = { rendre, calculer, gagnant, ouvrir };   // utile pour déboguer dans la console
});
