/** Resolve assignment from the same persisted agent/model records used by Settings.
 * Older office-layout projections contain coordinates and names only.
 */
export async function loadAgentDetails(api, agentId) {
 const agent=await api(`/agents/${encodeURIComponent(agentId)}`);
 if(!Object.hasOwn(agent,'model_id')) throw new Error('Datele angajatului nu includ alocarea modelului.');
 if(!agent.model_id) return {...agent,model_name:null,model_is_available:false,provider_name:null};
 if(!agent.provider_id) throw new Error('Modelul alocat nu are furnizor.');
 const [catalog,providers]=await Promise.all([
  api(`/providers/${encodeURIComponent(agent.provider_id)}/models`), api('/providers/'),
 ]);
 const model=catalog.models.find(m=>m.id===agent.model_id&&m.provider_id===agent.provider_id);
 if(!model) throw new Error('Modelul alocat nu a fost găsit în catalogul furnizorului. Verifică în Setări.');
 return {...agent,model_name:model.model_name,model_is_available:model.is_available===true,
  provider_name:providers.providers.find(p=>p.id===agent.provider_id)?.name || 'Furnizor necunoscut'};
}
