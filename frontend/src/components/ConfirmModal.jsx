export default function ConfirmModal({ interrupt, onAnswer, busy }) {
  if (!interrupt) return null;
  return (
    <div className="modal-backdrop">
      <div className="modal">
        <div className="modal-title">Confirm change</div>
        <div className="modal-message">{interrupt.message}</div>
        <div className="modal-actions">
          <button disabled={busy} className="btn btn-decline" onClick={() => onAnswer(false)}>
            Decline
          </button>
          <button disabled={busy} className="btn btn-confirm" onClick={() => onAnswer(true)}>
            Confirm
          </button>
        </div>
      </div>
    </div>
  );
}
