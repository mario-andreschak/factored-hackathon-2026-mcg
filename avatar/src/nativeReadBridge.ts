import { classifyMood } from './domain';

/** A deliberately narrow read request, separate from cinematic mood cues. */
export function isNativeReadRequest(text: string): boolean {
  const message = text.trim();
  if (!message || message.length > 2000) return false;
  const t = message.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase();
  if (!['inquiry', 'dispute'].includes(classifyMood(message).intent)) return false;
  // The installed Savia agent can read; it cannot commit account actions.
  if (/\b(refund\w*|chargeback|cancel\w*|block\w*|freeze\w*|send|pay|withdraw\w*|purchase\w*|delete\w*|human|agent|reembol\w*|bloque\w*|congel\w*|enviar|envi\w*|mandar|mand\w*|pagar|pagu\w*|retirar|retir\w*|sacar|saqu\w*|comprar|compr\w*|borrar|apagar|apag\w*|excluir|exclu\w*|delet\w*|humano|asesor|assessor|atendente|estorn\w*|devolv\w*|ressarc\w*)\b/.test(t)) return false;
  const actionText = t.replace(/\b(?:an|the|is|has) open\b/g, 'existing');
  if (/\b(file|open|start|submit|raise|create|hacer|abrir|iniciar|presentar|crear|abra|inicie|criar|crie|apresentar|apresente|registrar|registre|protocol\w*|solicitar|solicite)\b.{0,45}\b(disput\w*|claim|complaint|reclamo|disputa|contestac\w*|reclamac\w*)\b/.test(actionText)) return false;
  if (/\b(contestar|conteste|contestem)\b/.test(t)) return false;
  if (/\b(transfer|move|change|update|transferir|transfir\w*|transfere|transferem|mover|mova|cambiar|actualizar|alter\w*|atualiz\w*|trocar|troque|mudar|mude)\b/.test(t)) return false;
  if (/\b(faca|fazer|realiz\w*|efetu\w*)\b.{0,45}\b(transfer\w*|pagamento|saque|compra)\b/.test(t)) return false;
  if (/\b(abra|abrir|crie|criar|inicie|iniciar|registre|registrar|ative|ativar|autorize|autorizar|habilite|habilitar|solicite|solicitar|faca|fazer|efetue|efetuar|realize|realizar)\b.{0,45}\b(conta|cartao|credito|assinatura|cadastro|endereco|limite|debito|chave|pix)\b/.test(t)) return false;
  if (/\b(ignore|override|execute|run code|ignorar|ejecutar|execut\w*|sobrepor|substitua|rode codigo)\b/.test(t) || /[<>`]/.test(message)) return false;
  return /\b(what|why|how|when|which|whether|check|explain|show|tell|review|look|list|status|cuanto|quanto|que|como|cuando|quando|cual|qual|quais|revisa\w*|revis\w*|explica\w*|expliq\w*|muestra\w*|mostr\w*|consulta\w*|consult\w*|verifiq\w*|confir\w*|veja|liste|listar|detalh\w*|diga|dizer|informe|situacao|estado)\b/.test(t);
}
