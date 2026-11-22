"""One explicitly opted-in direct-to-mailbox retry, owned by the app loop."""
import LXMF


def retry_via_mailbox(message, router, selected_node, current_node, *, automatic):
    if (not automatic or selected_node is None or current_node != selected_node
            or message.state != LXMF.LXMessage.FAILED
            or message.desired_method == LXMF.LXMessage.PROPAGATED
            or getattr(message, "_next_relay_retried", False)):
        return False
    message._next_relay_retried = True
    message.packed = None
    message.delivery_attempts = 0
    if hasattr(message, "next_delivery_attempt"):
        del message.next_delivery_attempt
    message.desired_method = LXMF.LXMessage.PROPAGATED
    try:
        router.set_outbound_propagation_node(current_node)
        router.handle_outbound(message)
    except Exception:
        message.state = LXMF.LXMessage.FAILED
        return False
    return True
