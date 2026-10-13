import { autonomyModeLabel } from './governance.js';
import { nextRunWords } from './side_readout.js';

export function autonomyOverview(snapshot, jobs, escape) {
  const policy = snapshot?.policy;
  const next = nextRunWords(jobs, { stopped: policy?.autonomy_stopped, timeZone: snapshot?.studio?.timezone });
  const rows = [
    ['Mod', policy ? autonomyModeLabel(policy.autonomy_mode) : 'Necunoscut'],
    ['Mediu', policy?.environment === 'TEST' ? 'Test' : policy?.environment === 'PRODUCTION' ? 'Producție' : 'Necunoscut'],
    ['Lucru automat', !policy ? 'Necunoscut' : policy.autonomy_stopped ? 'Oprit' : 'Permis în limitele setate'],
    ['Următoarea rulare', next.value],
    ['Fus orar', snapshot?.studio?.timezone || 'Necunoscut'],
  ];
  return `<dl class="autonomy-summary">${rows.map(([label, value]) => `<div><dt>${escape(label)}</dt><dd>${escape(value)}</dd></div>`).join('')}</dl>
    <div class="autonomy-shortcuts"><button class="secondary" type="button" data-autonomy-go="policy">Mod și permisiuni</button><button class="secondary" type="button" data-autonomy-go="schedule">Program zilnic</button><button class="secondary" type="button" data-autonomy-go="providers">Conexiuni</button></div>`;
}
