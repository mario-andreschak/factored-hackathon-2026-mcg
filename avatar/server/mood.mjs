/** Presentation cues only: never identity, diagnosis, or account authorization. */
export function classifyMood(text) {
  const t = text.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase();
  const human = /\b(stolen|hacked|threat|suicid\w*|emergency|emergenc\w*|robad\w*|robar\w*|robo|amenaza\w*|hacke\w*|roubad\w*|roubar\w*|roubo|furt\w*|ameac\w*|invad\w*)\b/.test(t);
  const dispute = /\b(disput\w*|unrecogni[sz]\w*|charged twice|double charge|no reconozco|cobraron dos|reclamo|chargeback|contest\w*|nao reconhec\w*|cobrad\w* (?:duas|2) vezes|cobraram (?:duas|2)|cobranca duplicada|pagamento duplicado|reembolsos?)\b/.test(t);
  const inquiry = /\b(charges?|payments?|transactions?|transfers?|balances?|pagos?|transacci(?:on|ones)|saldos?|cobros?|movimientos?|pagamentos?|transac(?:ao|oes)|transferencias?|cobrad\w*|cobrancas?|movimentac(?:ao|oes)|extratos?)\b/.test(t);
  const intent = human ? 'human' : dispute ? 'dispute' : inquiry ? 'inquiry' : 'other';
  if (human || /\b(overwhelm\w*|anxious|anxiety|scared|worried|panic\w*|stress\w*|sad|exhaust\w*|tired|afraid|agobiad\w*|ansio\w*|miedo|medo|preocup\w*|triste|cansad\w*|sobrecarregad\w*|estressad\w*|esgotad\w*|exaust\w*|receio)\b/.test(t)) {
    return { avatar: 'moss', intent, reason: 'Un poco de espacio para respirar.' };
  }
  if (/\b(quick\w*|fast|asap|urgent|angry|furious|let.s go|let us go|ready to go|get moving|hyped|excited|pumped|energetic|rapid\w*|urgente|enojad\w*|furios\w*|zangad\w*|irritad\w*|animad\w*|empolgad\w*|energic\w*|vamos nessa|bora)\b/.test(t)) {
    return { avatar: 'spark', intent, reason: 'Un poco de energía para avanzar.' };
  }
  if (/\b(plan|planos?|explain|business|compare|review|organize|budget|reason|analys\w*|explic\w*|expliq\w*|presupuesto|revis\w*|compar\w*|organiz\w*|orcament\w*|analis\w*|negocios?)\b/.test(t) || intent !== 'other') {
    return { avatar: 'orbit', intent, reason: 'Claridad para el siguiente paso.' };
  }
  return { avatar: 'moss', intent, reason: 'Empecemos en un lugar tranquilo.' };
}
