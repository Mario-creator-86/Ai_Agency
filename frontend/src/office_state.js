import { bubblePages, bubbleDurationMs } from './speech_bubble.js';
/**
 * Office State Manager.
 *
 * Bridges backend snapshot data and real-time WebSocket domain events
 * to visual canvas elements (agents, speech bubbles, project tokens).
 */

/**
 * Which department each workflow stage belongs to, by the zone id the backend serves.
 *
 * The stage-to-place mapping used to be a table of hardcoded pixel coordinates. When the
 * building was rebuilt — taller, with a double-height ground floor — the table was not, so
 * research was drawn in the executive suite and publishing floated outside the wall. Worse,
 * the lift is dispatched by which zone a token lands in, so wrong coordinates sent the cab to
 * the wrong floor. Naming the department instead and asking the layout where it is keeps the
 * token where the backend actually put the work, whatever the building looks like.
 */
const STAGE_ZONES = {
  DISCOVERY: 'director_suite',
  IDEA_SELECTION: 'director_suite',
  RESEARCH: 'research_lab',
  FACT_CHECK: 'research_lab',
  SCRIPTING: 'script_room',
  HOOK_OPTIMIZATION: 'script_room',
  STORYBOARD: 'script_room',
  VOICE_GENERATION: 'audio_booth',
  ASSET_GENERATION: 'video_studio',
  VIDEO_GENERATION: 'video_studio',
  EDITING: 'video_studio',
  QUALITY_CONTROL: 'video_studio',
  READY_TO_PUBLISH: 'publish_desk',
  PUBLISHING: 'publish_desk',
  PUBLISHED: 'publish_desk',
  ANALYTICS: 'director_suite',
  LEARNING: 'director_suite',
};

export class OfficeState {
  constructor() {
    this.layout = null;
    this.agents = [];
    this.speechBubbles = [];
    this.projectTokens = [];
  }

  initFromLayout(layout) {
    this.layout = layout;
    this.agents = (layout.assignments || []).map(a => ({
      ...a,
      id: a.agent_id,
      runtime_state: a.runtime_state || 'IDLE',
      lifecycle: a.lifecycle || 'ACTIVE',
    }));
  }

  setAgents(agentsList) {
    const byId = new Map(this.agents.map(a => [a.id || a.agent_id, a]));
    for (const a of agentsList) {
      const id = a.id || a.agent_id;
      if (byId.has(id)) {
        Object.assign(byId.get(id), a);
      }
    }
  }

  addSpeechBubble(agentId, text, durationMs = null) {
    const agent = this.agents.find(a => (a.id || a.agent_id) === agentId);
    if (!agent) return;

    // The bubble stays up as long as reading the whole answer takes: it pages through the
    // text at a readable pace, so a long answer is long, never cut.
    const pages = bubblePages(text);
    const bubble = {
      id: `${agentId}_${Date.now()}`,
      agentId,
      text,
      pages,
      x: agent.x,
      y: agent.y,
      createdAt: Date.now(),
      expiresAt: Date.now() + (durationMs ?? bubbleDurationMs(pages)),
    };

    // Remove existing bubble for this agent
    this.speechBubbles = this.speechBubbles.filter(b => b.agentId !== agentId);
    this.speechBubbles.push(bubble);
  }

  /**
   * Where a token for this stage stands, taken from the layout the backend serves.
   *
   * Returns null while no layout has arrived, so a token is never placed at a guessed point.
   */
  coordsForStage(stage) {
    const zones = (this.layout && this.layout.zones) || [];
    if (!zones.length) return null;
    const zoneId = STAGE_ZONES[stage];
    const zone = zones.find(z => z.id === zoneId) || zones.find(z => z.floor === 0) || zones[0];
    const desks = zone.desks || [];
    // Beside the desk that does this work, or in the middle of the department if it has none.
    const x = desks.length
      ? Math.round(desks.reduce((sum, d) => sum + d.x, 0) / desks.length)
      : Math.round(zone.x + zone.width / 2);
    return { x, y: zone.y + zone.height - 40 };
  }

  updateProjectToken(workflowId, stage, title = 'Video Short') {
    const coords = this.coordsForStage(stage);
    if (!coords) return;
    const existing = this.projectTokens.find(t => t.id === workflowId);
    if (existing) {
      existing.stage = stage;
      existing.x = coords.x;
      existing.y = coords.y;
    } else {
      this.projectTokens.push({
        id: workflowId,
        title,
        stage,
        x: coords.x,
        y: coords.y,
      });
    }
  }

  cleanupExpiredBubbles() {
    const now = Date.now();
    this.speechBubbles = this.speechBubbles.filter(b => b.expiresAt > now);
  }

  handleDomainEvent(event) {
    const type = event.event_type;
    const payload = event.payload || {};

    if (type === 'agent.state_changed') {
      const agent = this.agents.find(a => (a.id || a.agent_id) === event.aggregate_id);
      if (agent) {
        agent.runtime_state = payload.runtime_state || agent.runtime_state;
      }
    } else if (type === 'agent.message_sent') {
      this.addSpeechBubble(event.aggregate_id, payload.text || payload.content || 'Working on task...');
    } else if (type === 'agent.paused') {
      const agent = this.agents.find(a => (a.id || a.agent_id) === event.aggregate_id);
      if (agent) {
        agent.lifecycle = 'PAUSED';
      }
    } else if (type === 'agent.resumed') {
      const agent = this.agents.find(a => (a.id || a.agent_id) === event.aggregate_id);
      if (agent) {
        agent.lifecycle = 'ACTIVE';
      }
    } else if (type === 'agent.run_completed') {
      const agent = this.agents.find(a => (a.id || a.agent_id) === payload.agent_id);
      if (agent) {
        agent.runtime_state = 'IDLE';
        if (payload.status === 'SUCCEEDED') {
          this.addSpeechBubble(agent.id, `Completed: ${payload.task_type || 'task'} ✓`, 4000);
        }
      }
    } else if (type.startsWith('workflow.')) {
      if (payload.current_stage) {
        this.updateProjectToken(event.aggregate_id, payload.current_stage);
      }
    }
  }
}
