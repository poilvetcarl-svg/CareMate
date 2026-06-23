/* =============================================
   VAXAI, Main JavaScript
   ============================================= */

// ===== STATE =====
let currentStep = 1;
let chatHistory = [];
let chatOpen = true;
let assessmentData = {};

// ===== INIT =====
document.addEventListener('DOMContentLoaded', () => {
  initNavbar();
  initCounters();
  initSexToggle();
  initNoneCondition();
  initAgeSlider();
  initScrollAnimations();
  initChatbot();
});

// ===== NAVBAR =====
function initNavbar() {
  const navbar = document.getElementById('navbar');
  if (!navbar) return;
  window.addEventListener('scroll', () => {
    navbar.classList.toggle('scrolled', window.scrollY > 60);
  });
}

// ===== ANIMATED COUNTERS =====
function initCounters() {
  const counters = document.querySelectorAll('[data-count]');
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        animateCounter(entry.target);
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.5 });
  counters.forEach(c => observer.observe(c));
}

function animateCounter(el) {
  const target = parseInt(el.dataset.count);
  const duration = 1800;
  const step = target / (duration / 16);
  let current = 0;
  const timer = setInterval(() => {
    current += step;
    if (current >= target) { current = target; clearInterval(timer); }
    el.textContent = Math.floor(current).toLocaleString();
  }, 16);
}

// ===== SCROLL ANIMATIONS =====
function initScrollAnimations() {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('animate-in');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.1 });
  document.querySelectorAll('.video-card, .feature-img-card, .how-step').forEach(el => observer.observe(el));
}

// ===== SEX TOGGLE (show/hide pregnancy) =====
function initSexToggle() {
  document.querySelectorAll('input[name="sex"]').forEach(input => {
    input.addEventListener('change', () => {
      const pg = document.getElementById('pregnancyGroup');
      if (pg) pg.style.display = input.value === 'female' ? 'block' : 'none';
    });
  });
}

// ===== AGE SLIDER =====
function initAgeSlider() {
  const slider = document.getElementById('ageSlider');
  if (slider) updateAge(slider.value);
}

function updateAge(val) {
  const display = document.getElementById('ageValue');
  if (display) display.textContent = val;
  const slider = document.getElementById('ageSlider');
  if (slider) {
    const pct = ((val - 18) / (100 - 18)) * 100;
    slider.style.background = `linear-gradient(to right, var(--accent) ${pct}%, rgba(255,255,255,0.1) ${pct}%)`;
  }
}

// ===== NONE CONDITION =====
function initNoneCondition() {
  const noneEl = document.getElementById('noneCondition');
  if (!noneEl) return;
  noneEl.addEventListener('change', () => {
    if (noneEl.checked) {
      document.querySelectorAll('input[name="conditions"]').forEach(cb => {
        if (cb.value !== 'none') cb.checked = false;
      });
    }
  });
  document.querySelectorAll('input[name="conditions"]').forEach(cb => {
    if (cb.value !== 'none') {
      cb.addEventListener('change', () => {
        if (cb.checked && noneEl.checked) noneEl.checked = false;
      });
    }
  });
}

// ===== STEP NAVIGATION =====
function goToStep(step) {
  // Validate step 1 before advancing
  if (currentStep === 1 && step > 1) {
    const nameVal = document.getElementById('patientNameInput')?.value.trim();
    if (!nameVal) {
      const inp = document.getElementById('patientNameInput');
      inp.style.borderColor = '#ef4444';
      inp.focus();
      inp.placeholder = 'Please enter your name to continue';
      return;
    }
    const sexSelected = document.querySelector('input[name="sex"]:checked');
    if (!sexSelected) {
      const grp = document.getElementById('sexGroup');
      if (grp) {
        grp.style.outline = '2px solid #ef4444';
        grp.style.borderRadius = '12px';
        grp.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
      const hint = document.getElementById('sexHint');
      if (hint) hint.style.display = 'block';
      return;
    }
    // Clear validation styles
    const grp = document.getElementById('sexGroup');
    if (grp) { grp.style.outline = ''; }
    const hint = document.getElementById('sexHint');
    if (hint) hint.style.display = 'none';
    // Save name to localStorage so consultation can use it
    try { localStorage.setItem('patientName', nameVal); } catch(e) {}
  }

  const current = document.getElementById(`step${currentStep}`);
  const next = document.getElementById(`step${step}`);
  if (!next) return;

  current.classList.add('hidden');
  next.classList.remove('hidden');

  document.querySelectorAll('.step').forEach(s => {
    const n = parseInt(s.dataset.step);
    s.classList.remove('active', 'done');
    if (n === step) s.classList.add('active');
    else if (n < step) s.classList.add('done');
  });

  currentStep = step;
  document.getElementById('assessmentForm')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ===== TRAVEL TOGGLE =====
function toggleTravel(show) {
  const el = document.getElementById('travelRegions');
  if (el) el.classList.toggle('hidden', !show);
}

// ===== FORM DATA COLLECTION =====
function collectFormData() {
  const age = document.getElementById('ageSlider')?.value || 35;
  const sex = document.querySelector('input[name="sex"]:checked')?.value || 'not_specified';
  const pregnant = document.querySelector('input[name="pregnant"]:checked')?.value || 'no';
  const vaccinated = document.querySelector('input[name="vaccinated_recently"]:checked')?.value || 'no';
  const patient_name = document.getElementById('patientNameInput')?.value.trim() || '';

  const conditions = [];
  document.querySelectorAll('input[name="conditions"]:checked').forEach(cb => {
    if (cb.value !== 'none') conditions.push(cb.value);
  });

  const travelRegions = [];
  document.querySelectorAll('input[name="travel_regions"]:checked').forEach(cb => {
    travelRegions.push(cb.value);
  });

  // Persist name so consultation page picks it up
  if (patient_name) {
    try { localStorage.setItem('patientName', patient_name); } catch(e) {}
  }

  return { age: parseInt(age), sex, pregnant, vaccinated_recently: vaccinated, conditions, travel_regions: travelRegions, patient_name };
}

// ===== SUBMIT ASSESSMENT =====
async function submitAssessment() {
  const data = collectFormData();
  assessmentData = data;

  const overlay = document.getElementById('loadingOverlay');
  overlay?.classList.remove('hidden');

  try {
    const res = await fetch('/api/recommend', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    const result = await res.json();

    overlay?.classList.add('hidden');
    renderResults(result);

  } catch (err) {
    overlay?.classList.add('hidden');
    alert('Error getting recommendations. Please check your connection and try again.');
    console.error(err);
  }
}

// ===== RENDER RESULTS =====
function renderResults(result) {
  const section = document.getElementById('resultsSection');
  if (!section) return;
  section.classList.remove('hidden');
  section.scrollIntoView({ behavior: 'smooth', block: 'start' });

  // AI Summary
  const summaryEl = document.getElementById('aiSummaryText');
  if (summaryEl && result.ai_summary) {
    typeText(summaryEl, result.ai_summary);
  }

  // Risk score
  renderRiskScore(result.risk);

  // Vaccines
  renderVaccines(result.vaccines);

  // Preventive screenings / health checks
  renderScreenings(result.screenings || []);

  // Vaccine count
  const countEl = document.getElementById('vaccineCount');
  if (countEl) countEl.textContent = result.vaccines.length;

  // Save full assessment to localStorage so consultation can reference it
  const patientName = (assessmentData || {}).patient_name || '';
  const assessmentPayload = {
    risk: result.risk,
    vaccines: result.vaccines.map(v => v.name),
    ai_summary: result.ai_summary,
    form: assessmentData || {},
    patient_name: patientName
  };
  try {
    localStorage.setItem('lastAssessment', JSON.stringify(assessmentPayload));
    if (patientName) localStorage.setItem('patientName', patientName);
  } catch(e) {}

  // Inject "Discuss with a Doctor" section above CTA
  renderDoctorOffer(result);
}

// ===== PREVENTIVE SCREENINGS =====
// ===== CORAL LINE ICONS (results section) =====
const ICON_SVG = {
  drop:   '<path d="M12 3s6 6 6 10.5a6 6 0 11-12 0C6 9 12 3 12 3z"/>',
  heart:  '<path d="M12 20S4 15 4 9.5A3.5 3.5 0 0112 7a3.5 3.5 0 018 2.5C20 15 12 20 12 20z"/><path d="M6 12h2l1.5-3 2 5 1.5-2H18"/>',
  stetho: '<path d="M6 3v5a4 4 0 008 0V3"/><path d="M10 14v1a5 5 0 0010 0v-1"/><circle cx="19.5" cy="11" r="2"/>',
  ribbon: '<path d="M10 13l-3 8 3-1.5L12 21l2.5-1.5 3 1.5-3-8"/><path d="M9.5 14C7.5 11.5 7 9.5 7 8a5 5 0 0110 0c0 1.5-.5 3.5-2.5 6"/>',
  lungs:  '<path d="M12 3v8"/><path d="M12 9c0 6-1 9-3.5 9C6 18 5 16 5 13c0-2 .6-3.6 1.6-4.6"/><path d="M12 9c0 6 1 9 3.5 9 2.5 0 3.5-2 3.5-5 0-2-.6-3.6-1.6-4.6"/>',
  vial:   '<path d="M9 3h6M10 3v12a2 2 0 004 0V3"/><path d="M10 9.5h4"/>',
  bone:   '<path d="M8 16a2 2 0 11-1.6-3.2A2 2 0 118 9l1-1 6 6-1 1a2 2 0 11-3.4 1.6A2 2 0 018 16z"/><path d="M16 8a2 2 0 111.6-3.2A2 2 0 1116 1"/>',
  eye:    '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="2.5"/>',
  kidney: '<path d="M14 5c-3 0-5 3-5 7s2 7 5 7c1.7 0 3-1.3 3-3 0-1.2-.6-1.8-.6-2.5S17 9.5 17 8.2C17 6.4 15.7 5 14 5z"/>',
  shield: '<path d="M12 3l7 3v5c0 4.5-3 8.5-7 10-4-1.5-7-5.5-7-10V6l7-3z"/><path d="M9 12l2 2 4-4"/>',
  pulse:  '<path d="M3 12h4l2-5 3 10 2.5-5H21"/>',
};
const SCREENING_ICON = {
  blood_pressure: 'stetho', lipid_panel: 'heart', diabetes_screen: 'drop',
  cervical_cancer: 'ribbon', breast_cancer: 'ribbon', colorectal_cancer: 'ribbon',
  lung_cancer: 'lungs', hepatitis_screen: 'vial', hiv_screen: 'vial',
  osteoporosis: 'bone', prostate: 'stetho', eye_exam_diabetic: 'eye',
  kidney_function: 'kidney', tb_screen: 'lungs', aaa_screen: 'pulse',
};
function coralSvg(shape) {
  return `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#FF6B6B" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${ICON_SVG[shape] || ICON_SVG.shield}</svg>`;
}
function screeningIcon(key) { return coralSvg(SCREENING_ICON[key] || 'pulse'); }

function renderScreenings(screenings) {
  document.getElementById('screeningsSection')?.remove();
  if (!screenings.length) return;

  // Top 3 are what the user should actually act on; the rest stays one click away
  const top = screenings.slice(0, 3);
  const rest = screenings.slice(3);

  const row = (s, highlight) => `
    <div style="display:flex;align-items:flex-start;gap:12px;padding:${highlight ? '14px 16px' : '11px 16px'};border-bottom:1px solid rgba(255,107,107,0.1);background:white">
      <div style="width:36px;height:36px;border-radius:10px;background:#FFF8F5;border:1px solid rgba(255,107,107,0.12);display:flex;align-items:center;justify-content:center;flex-shrink:0">${screeningIcon(s.key)}</div>
      <div style="flex:1;min-width:0">
        <div style="display:flex;align-items:baseline;gap:8px;flex-wrap:wrap">
          <span style="font-size:14px;font-weight:700;color:#1A0A00">${s.name}</span>
          <span style="font-size:11px;color:#A07850">${s.frequency}</span>
        </div>
        <div style="font-size:12px;color:#6B4423;line-height:1.5;margin-top:2px">${s.why}</div>
      </div>
    </div>`;

  const restHtml = rest.length ? `
    <div id="moreScreenings" style="display:none">${rest.map(s => row(s, false)).join('')}</div>
    <button onclick="toggleMoreScreenings(this)" style="width:100%;padding:12px;background:#FFF8F5;border:none;border-top:1px solid rgba(255,107,107,0.1);font-size:13px;font-weight:700;color:var(--coral-dark,#E55555);cursor:pointer;font-family:inherit">
      Show ${rest.length} more checks ▾
    </button>` : '';

  const html = `
  <div id="screeningsSection" class="vaccines-section" style="margin-top:32px">
    <h3 class="vaccines-title">
      Health Checks for Your Age
      <span class="vaccines-count">${screenings.length}</span>
    </h3>
    <p style="font-size:13px;color:#6B4423;margin:-12px 0 16px">Start with these ${top.length}, they matter most for your profile.</p>
    <div style="border:1px solid rgba(255,107,107,0.12);border-radius:14px;overflow:hidden">
      ${top.map(s => row(s, true)).join('')}
      ${restHtml}
    </div>
  </div>`;

  const vaccinesSection = document.querySelector('.vaccines-section:not(#screeningsSection)');
  if (vaccinesSection) vaccinesSection.insertAdjacentHTML('afterend', html);
}

function toggleMoreScreenings(btn) {
  const more = document.getElementById('moreScreenings');
  const open = more.style.display !== 'none';
  more.style.display = open ? 'none' : '';
  btn.innerHTML = open ? `Show ${more.children.length} more checks ▾` : 'Show less ▴';
}

// ===== DOCTOR OFFER (shown after results) =====
function renderDoctorOffer(result) {
  // Remove any existing offer
  document.getElementById('doctorOfferSection')?.remove();

  const vaccineList = result.vaccines.slice(0, 4).map(v => v.name).join(', ');
  const riskLevel   = result.risk.level;

  const html = `
  <div id="doctorOfferSection" style="
    margin: 32px 0;
    background: linear-gradient(135deg, rgba(124,58,237,0.08), rgba(59,130,246,0.05));
    border: 1px solid rgba(124,58,237,0.2);
    border-radius: 20px;
    padding: 28px;
  ">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
      <span style="font-size:22px"><i class="ti ti-microphone" style="color:var(--accent)"></i></span>
      <h3 style="font-size:19px;font-weight:800;color:#1e293b;margin:0">Talk to a Doctor About Your Results</h3>
    </div>
    <p style="font-size:14px;color:#64748b;margin:0 0 22px;line-height:1.6">
      Your AI doctor already knows your <strong>${riskLevel}</strong> profile and
      your ${result.vaccines.length} recommended vaccines.
      Start a live video consultation, no need to repeat yourself.
    </p>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">
      ${renderOfferDoctorCard(1, 'Dr. Budi Santoso', 'Internal Medicine & Infectious Disease', 'male')}
      ${renderOfferDoctorCard(2, 'Dr. Sari Dewi, Sp.PD', 'Vaccinology & Travel Medicine', 'female')}
    </div>
  </div>`;

  const anchor = document.getElementById('screeningsSection') || document.querySelector('.vaccines-section');
  if (anchor) {
    anchor.insertAdjacentHTML('afterend', html);
  }
}

function renderOfferDoctorCard(id, name, specialty, gender) {
  const videoUrl = gender === 'male'
    ? 'https://cdn.replica.tavus.io/39476/8558b349.mp4'
    : 'https://cdn.replica.tavus.io/20310/f5d5455f_normalized.mp4';
  return `
    <div style="
      background:#fff;border:1px solid rgba(124,58,237,0.15);border-radius:16px;
      padding:16px;display:flex;flex-direction:column;gap:12px;
      box-shadow:0 2px 12px rgba(124,58,237,0.06);
    ">
      <div style="display:flex;align-items:center;gap:12px">
        <div style="width:56px;height:56px;border-radius:50%;overflow:hidden;flex-shrink:0;border:2px solid rgba(124,58,237,0.2)">
          <video autoplay muted loop playsinline style="width:100%;height:100%;object-fit:cover;object-position:top">
            <source src="${videoUrl}" type="video/mp4">
          </video>
        </div>
        <div>
          <div style="font-size:14px;font-weight:700;color:#1e293b">${name}</div>
          <div style="font-size:11px;color:#7c3aed;font-weight:600;margin-top:2px">${specialty}</div>
          <div style="display:flex;align-items:center;gap:4px;margin-top:4px">
            <span style="width:7px;height:7px;border-radius:50%;background:#10b981;display:inline-block"></span>
            <span style="font-size:11px;color:#10b981;font-weight:600">Available Now</span>
          </div>
        </div>
      </div>
      <a href="/consultation/${id}" onclick="saveContextAndGo(event,${id})"
         style="display:block;background:linear-gradient(135deg,#7c3aed,#3b82f6);color:#fff;
                text-align:center;padding:10px 14px;border-radius:10px;text-decoration:none;
                font-size:13px;font-weight:700;transition:opacity .2s"
         onmouseover="this.style.opacity='.88'" onmouseout="this.style.opacity='1'">
        <i class="ti ti-video"></i> Discuss My Results
      </a>
    </div>`;
}

function saveContextAndGo(event, doctorId) {
  // Assessment is already saved, just let the link navigate naturally
  // (localStorage was set in renderResults)
}

// ===== TYPING EFFECT =====
function typeText(el, text, speed = 18) {
  el.textContent = '';
  let i = 0;
  const timer = setInterval(() => {
    el.textContent += text[i];
    i++;
    if (i >= text.length) clearInterval(timer);
  }, speed);
}

// ===== RISK SCORE =====
function renderRiskScore(risk) {
  // Positive framing: Prevention Score, higher = better protected
  const pScore = risk.prevention_score ?? (100 - risk.percentage);
  const pLabel = risk.prevention_label || risk.level;
  const pColor = risk.prevention_color || risk.color;

  const badgeEl = document.getElementById('riskBadge');
  if (badgeEl) {
    badgeEl.textContent = pLabel;
    badgeEl.style.background = pColor + '22';
    badgeEl.style.color = pColor;
    badgeEl.style.border = `1px solid ${pColor}44`;
    badgeEl.style.borderRadius = '100px';
    badgeEl.style.padding = '6px 16px';
    badgeEl.style.fontSize = '14px';
    badgeEl.style.fontWeight = '700';
  }

  const scoreEl = document.getElementById('riskScore');
  if (scoreEl) animateNumber(scoreEl, pScore, 1200);

  const arc = document.getElementById('gaugeArc');
  if (arc) {
    arc.style.stroke = pColor;
    const total = 298;
    const offset = total - (total * pScore / 100);
    setTimeout(() => { arc.style.strokeDashoffset = offset; }, 200);
  }

  // Factors, no emoji, no point numbers. Tag each as improvable or fixed.
  const improvable = [
    /vaccin/i, /overdue/i, /smoking/i, /obesity/i, /travel/i,
  ];
  const factorsList = document.getElementById('riskFactorsList');
  if (factorsList) {
    factorsList.innerHTML = risk.factors.map(f => {
      const canImprove = improvable.some(re => re.test(f.factor));
      const tag = canImprove
        ? '<span class="rf-tag rf-improve">Can improve</span>'
        : '<span class="rf-tag rf-fixed">Fixed</span>';
      return `<div class="risk-factor-item">
        <span class="risk-factor-label">${f.factor}</span>
        ${tag}
      </div>`;
    }).join('');
  }

  const adviceEl = document.getElementById('riskAdvice');
  if (adviceEl) adviceEl.textContent = risk.advice;
}

function animateNumber(el, target, duration) {
  let start = 0;
  const step = target / (duration / 16);
  const timer = setInterval(() => {
    start += step;
    if (start >= target) { start = target; clearInterval(timer); }
    el.textContent = Math.round(start);
  }, 16);
}

// ===== RENDER VACCINES =====
function renderVaccines(vaccines) {
  const grid = document.getElementById('vaccinesGrid');
  if (!grid) return;
  grid.innerHTML = '';

  const priority   = vaccines.filter(v => v.priority === 'high');
  const others     = vaccines.filter(v => v.priority !== 'high');

  function buildRows(list) {
    return list.map((v, i) => {
      const isCondBased   = Object.keys(v.clinical_details || {}).length > 0;
      // Influenza is high priority (PAPDI annual) but label differs from condition-based high-risk vaccines
      const priorityLabel = v.key === 'influenza' ? 'Annual Priority'
        : { high: 'High Risk', routine: 'Routine', recommended: 'Recommended', catch_up: 'Catch-up', travel: 'Travel' }[v.priority] || v.priority;
      const priorityClass = { high: 'vr-badge-high', routine: 'vr-badge-routine', recommended: 'vr-badge-rec', catch_up: 'vr-badge-catchup', travel: 'vr-badge-travel' }[v.priority] || 'vr-badge-rec';

      const primaryReason = isCondBased
        ? v.reasons.find(r => r.toLowerCase().includes('papdi') || r.toLowerCase().includes('due to') || r.toLowerCase().includes('condition')) || v.reasons[0]
        : v.reasons[0] || '';

      // Expanded clinical panel (hidden by default)
      const expandId = `vr-expand-${v.key}-${i}`;

      const clinicalHtml = Object.entries(v.clinical_details || {}).map(([cond, cd]) => {
        const condLabel = cond.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        return `
          <div class="vc-interaction">
            <div class="vc-interaction-label">⇌ HOW YOUR CONDITION AND THIS DISEASE INTERACT</div>
            <div class="vc-interaction-grid">
              <div class="vc-int-col">
                <div class="vc-int-col-header">${condLabel}</div>
                <div class="vc-int-col-text">${cd.condition_causes}</div>
              </div>
              <div class="vc-int-arrow">
                <div class="vc-int-arrow-icon">⇌</div>
                <div class="vc-int-arrow-label">TWO-WAY<br>LINK</div>
              </div>
              <div class="vc-int-col vc-int-col-right">
                <div class="vc-int-col-header">Disease Risk</div>
                <div class="vc-int-col-text">${cd.disease_worsens}</div>
              </div>
            </div>
            <div class="vc-plain-language"><i class="ti ti-message-circle" style="color:var(--accent)"></i> <em>In plain language:</em> ${cd.plain_language}</div>
          </div>
          <div class="vc-risk-block">
            <div class="vc-risk-label"><i class="ti ti-alert-triangle" style="color:var(--accent)"></i> If Not Vaccinated, What's The Risk?</div>
            <div class="vc-risk-text">${cd.if_not_vaccinated}</div>
          </div>
          <div class="vc-why-block">
            <div class="vc-why-label">+ Why Prioritise Now?</div>
            <div class="vc-why-text">${cd.why_now}</div>
          </div>
        `;
      }).join('');

      const reasonsHtml = !isCondBased && v.reasons.length > 0
        ? `<div class="vr-expand-reasons">${v.reasons.map(r => `<div class="vr-reason-item"><i class="ti ti-check" style="color:var(--accent)"></i> ${r}</div>`).join('')}</div>`
        : '';

      const sourcesHtml = v.sources && v.sources.length > 0
        ? `<div class="vc-footer" style="margin-top:12px">${v.sources.map(s => `<span class="source-tag">${s}</span>`).join('')}</div>`
        : '';

      const hasExpand = isCondBased || v.reasons.length > 0;

      return `
        <div class="vr-row" id="vr-row-${v.key}-${i}" style="animation-delay:${i * 0.05}s">
          <div class="vr-row-main" onclick="toggleVrExpand('${expandId}', this)">
            <div class="vr-icon-wrap">${coralSvg('shield')}</div>
            <div class="vr-row-content">
              <div class="vr-name-line">
                <span class="vr-name">${v.name}</span>
                ${isCondBased ? '<span class="vr-cond-badge">Condition-based</span>' : ''}
              </div>
              <div class="vr-subtitle">${primaryReason}</div>
            </div>
            <div class="vr-row-right">
              <span class="vr-badge ${priorityClass}">● ${priorityLabel}</span>
              ${hasExpand ? `<button class="vr-expand-btn" aria-label="Expand">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
              </button>` : ''}
            </div>
          </div>
          <div class="vr-expand-panel" id="${expandId}">
            <div class="vr-expand-inner">
              <div class="vr-schedule-chip"><i class="ti ti-calendar"></i> ${v.schedule}</div>
              ${clinicalHtml}
              ${reasonsHtml}
              ${sourcesHtml}
              <button class="vr-detail-btn" onclick="showVaccineModal(window.__vrVaccineMap['${v.key}'])">Full details →</button>
            </div>
          </div>
        </div>
      `;
    }).join('');
  }

  // Store vaccines for modal access (keyed by vaccine key)
  window.__vrVaccines = vaccines;
  window.__vrVaccineMap = {};
  vaccines.forEach(v => { window.__vrVaccineMap[v.key] = v; });

  if (priority.length > 0) {
    const section = document.createElement('div');
    section.className = 'vr-section';
    section.innerHTML = `
      <div class="vr-section-header vr-section-priority">
        <span class="vr-section-dot vr-dot-priority"></span>
        VACCINES TO PRIORITISE NOW
        <span class="vr-section-count">${priority.length}</span>
      </div>
      <div class="vr-rows">${buildRows(priority)}</div>
    `;
    grid.appendChild(section);
  }

  if (others.length > 0) {
    // Collapsed by default, most people only need to act on the priority list
    const section = document.createElement('div');
    section.className = 'vr-section';
    section.innerHTML = `
      <div class="vr-section-header vr-section-other" style="cursor:pointer;border-radius:10px"
           onclick="toggleOtherVaccines(this)">
        <span class="vr-section-dot vr-dot-other"></span>
        OTHER RECOMMENDED VACCINES
        <span class="vr-section-count">${others.length}</span>
        <svg class="vr-other-arrow" style="margin-left:8px;transition:transform .25s" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M6 9l6 6 6-6"/></svg>
      </div>
      <div class="vr-rows" style="display:none">${buildRows(others)}</div>
    `;
    grid.appendChild(section);
  }
}

function toggleOtherVaccines(header) {
  const rows = header.nextElementSibling;
  const arrow = header.querySelector('.vr-other-arrow');
  const open = rows.style.display !== 'none';
  rows.style.display = open ? 'none' : '';
  header.style.borderRadius = open ? '10px' : '10px 10px 0 0';
  if (arrow) arrow.style.transform = open ? '' : 'rotate(180deg)';
}

function toggleVrExpand(expandId, rowMain) {
  const panel = document.getElementById(expandId);
  if (!panel) return;
  const isOpen = panel.classList.contains('open');
  panel.classList.toggle('open', !isOpen);
  const btn = rowMain.querySelector('.vr-expand-btn');
  if (btn) btn.classList.toggle('rotated', !isOpen);
}

// ===== VACCINE MODAL =====
function showVaccineModal(vaccine) {
  const modal = document.getElementById('vaccineModal');
  const content = document.getElementById('modalContent');
  if (!modal || !content) return;

  const relHtml = Object.keys(vaccine.disease_relations).length > 0
    ? `<div style="margin-top:20px">
        <h4 style="font-size:14px;font-weight:700;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:12px"><i class="ti ti-alert-triangle" style="color:var(--accent)"></i> Your Condition Connections</h4>
        ${Object.entries(vaccine.disease_relations).map(([cond, explanation]) => `
          <div style="background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.2);border-radius:12px;padding:14px;margin-bottom:10px">
            <div style="font-size:12px;font-weight:700;color:#f87171;text-transform:uppercase;margin-bottom:6px">${cond.replace(/_/g,' ')}</div>
            <div style="font-size:13px;color:var(--text-secondary);line-height:1.7">${explanation}</div>
          </div>
        `).join('')}
      </div>`
    : '';

  content.innerHTML = `
    <img src="${vaccine.image}" alt="${vaccine.name}" style="width:100%;height:180px;object-fit:cover;border-radius:14px;margin-bottom:20px" onerror="this.style.display='none'" />
    <div style="display:flex;align-items:center;gap:14px;margin-bottom:16px">
      <div style="width:52px;height:52px;border-radius:14px;background:${vaccine.color}22;display:flex;align-items:center;justify-content:center;font-size:26px;flex-shrink:0">${vaccine.icon}</div>
      <div>
        <h2 style="font-size:22px;font-weight:800">${vaccine.name}</h2>
        <span class="vaccine-priority priority-${vaccine.priority}" style="margin-top:4px;display:inline-block">${vaccine.priority}</span>
      </div>
    </div>
    <p style="font-size:15px;color:var(--text-secondary);line-height:1.7;margin-bottom:16px">${vaccine.description}</p>
    <div style="background:rgba(124,58,237,0.1);border:1px solid rgba(124,58,237,0.2);border-radius:12px;padding:14px;margin-bottom:16px">
      <div style="font-size:12px;font-weight:700;color:#a78bfa;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px"><i class="ti ti-calendar" style="color:var(--accent)"></i> Schedule</div>
      <div style="font-size:14px">${vaccine.schedule}</div>
    </div>
    <div style="margin-bottom:16px">
      <div style="font-size:12px;font-weight:700;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px">Why it's recommended for you</div>
      ${vaccine.reasons.map(r => `<div style="display:flex;gap:8px;font-size:13px;color:var(--text-secondary);margin-bottom:6px"><span style="color:var(--accent)"><i class="ti ti-check"></i></span>${r}</div>`).join('')}
    </div>
    ${relHtml}
    ${vaccine.sources && vaccine.sources.length > 0 ? `
    <div class="vaccine-sources" style="margin-top:20px">
      <div style="font-size:11px;font-weight:700;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px"><i class="ti ti-book" style="color:var(--accent)"></i> Sources</div>
      <div style="display:flex;flex-wrap:wrap;gap:6px">
        ${vaccine.sources.map(s => `<span class="source-tag">${s}</span>`).join('')}
      </div>
    </div>` : ''}
    <a href="/teleconsultation" target="_blank" class="btn-primary" style="width:100%;justify-content:center;margin-top:16px;display:flex">Book Vaccination Consultation →</a>
  `;

  modal.classList.remove('hidden');
}

function showRelationDetail(vaccineKey, condition) {
  // This is handled by the card click handler for now
}

function closeModal() {
  document.getElementById('vaccineModal')?.classList.add('hidden');
}

// ===== RESET =====
function resetAssessment() {
  document.getElementById('resultsSection')?.classList.add('hidden');
  goToStep(1);
  document.getElementById('assessment')?.scrollIntoView({ behavior: 'smooth' });
}

// ===== SCROLL TO ASSESSMENT =====
function scrollToAssessment() {
  document.getElementById('assessment')?.scrollIntoView({ behavior: 'smooth' });
}

// ===== CHATBOT =====
function initChatbot() {
  const widget = document.getElementById('chatbotWidget');
  if (!widget) return;
  // Start collapsed everywhere, the assistant shouldn't cover page content uninvited
  widget.classList.add('collapsed');
  chatOpen = false;
}

function toggleChat() {
  const widget = document.getElementById('chatbotWidget');
  chatOpen = !chatOpen;
  widget?.classList.toggle('collapsed', !chatOpen);
}

async function sendMessage() {
  const input = document.getElementById('chatInput');
  if (!input) return;
  const msg = input.value.trim();
  if (!msg) return;

  input.value = '';
  input.disabled = true;
  appendMessage('user', msg);
  chatHistory.push({ role: 'user', content: msg });

  const thinking = appendThinking();

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg, history: chatHistory })
    });
    const data = await res.json();
    thinking.remove();

    if (data.error) {
      appendMessage('bot', data.reply, 'error');
    } else {
      appendMessage('bot', data.reply);
      chatHistory.push({ role: 'assistant', content: data.reply });
    }
  } catch {
    thinking.remove();
    appendMessage('bot', 'Connection error, please check your internet and try again.');
  } finally {
    input.disabled = false;
    input.focus();
  }
}

function sendSuggestion(text) {
  const input = document.getElementById('chatInput');
  if (input) { input.value = text; sendMessage(); }
  document.querySelector('.chat-suggestions')?.remove();
}

function appendMessage(role, text, type) {
  const container = document.getElementById('chatMessages');
  if (!container) return;
  const div = document.createElement('div');
  div.className = `chat-message ${role}`;
  const errorStyle = type === 'error' ? 'style="background:rgba(239,68,68,0.1);border-color:rgba(239,68,68,0.3);color:#fca5a5"' : '';
  div.innerHTML = `<div class="chat-bubble" ${errorStyle}>${escapeHtml(text)}</div>`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

function appendThinking() {
  const container = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = 'chat-message bot';
  div.innerHTML = '<div class="chat-bubble chat-thinking"><span></span><span></span><span></span></div>';
  container?.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

function escapeHtml(text) {
  return text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
}

// ===== VIDEO MODAL (YouTube embed) =====
function openVideoModal(youtubeId, title) {
  const modal = document.getElementById('videoModal');
  const iframe = document.getElementById('videoIframe');
  const titleEl = document.getElementById('videoModalTitle');
  if (!modal || !iframe) return;
  titleEl.textContent = title;
  iframe.src = `https://www.youtube.com/embed/${youtubeId}?autoplay=1&rel=0&modestbranding=1`;
  modal.classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

function closeVideoModal() {
  const modal = document.getElementById('videoModal');
  const iframe = document.getElementById('videoIframe');
  if (!modal) return;
  iframe.src = '';
  modal.classList.add('hidden');
  document.body.style.overflow = '';
}

// Keep old name as alias for any remaining calls
function playVideo(card, url) { /* replaced by openVideoModal */ }

// ===== KEYBOARD SHORTCUTS =====
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeModal();
    closeVideoModal();
    document.getElementById('bookingModal')?.classList.add('hidden');
  }
});
