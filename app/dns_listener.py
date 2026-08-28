import asyncio
import random
import re
from datetime import UTC, datetime, timedelta

from app.core import get_logger, settings
from app.database import SessionLocal
from app.models import DnsQuery

logger = get_logger(__name__)

# Matches RouterOS's `topics=dns` syslog line, e.g.:
#   dns,packet,info query from 10.5.50.23: #56091 www.google.com. type=A class=IN
# Tolerant of the port sometimes appended to the client address and of minor
# spacing/format differences between RouterOS versions. IPv4 only — MikroTik
# Hotspot client pools are IPv4 in every deployment this app targets.
QUERY_LINE_RE = re.compile(
    r"query from (?P<ip>\d{1,3}(?:\.\d{1,3}){3})(?::\d+)?[,:].*?(?P<domain>[A-Za-z0-9_.-]+)\.\s*type=",
)

# Kenyan and a handful of common international two-part public suffixes —
# without this, "kra.go.ke" would be reduced to the meaningless "go.ke"
# rather than the actual registrable domain. Deliberately a short hardcoded
# list rather than a full public-suffix-list dependency (unnecessary weight
# for what this needs).
TWO_PART_SUFFIXES = {
    "co.ke", "go.ke", "or.ke", "ac.ke", "ne.ke", "me.ke", "info.ke", "sc.ke",
    "co.uk", "org.uk", "gov.uk", "ac.uk", "co.za", "co.tz", "co.ug", "com.au",
}

PRUNE_AFTER_DAYS = 30


def registrable_domain(hostname: str) -> str:
    """Reduce a hostname to its top-level/registrable domain, e.g. "www.kra.go.ke" -> "kra.go.ke"."""
    labels = hostname.lower().strip(".").split(".")

    if len(labels) <= 2:
        return ".".join(labels)

    if ".".join(labels[-2:]) in TWO_PART_SUFFIXES:
        return ".".join(labels[-3:])

    return ".".join(labels[-2:])


def parse_query_line(line: str) -> tuple[str, str] | None:
    match = QUERY_LINE_RE.search(line)

    if not match:
        return None

    return match.group("ip"), registrable_domain(match.group("domain"))


class DnsSyslogProtocol(asyncio.DatagramProtocol):
    """
    Minimal UDP syslog receiver — RouterOS's `/system logging action set
    remote` sends plain BSD-syslog-formatted UDP datagrams, one per log
    line. This doesn't validate/parse the syslog envelope itself (PRI,
    timestamp, hostname) since only the DNS query text within it matters.
    """

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            line = data.decode("utf-8", errors="replace")
        except Exception:
            return

        parsed = parse_query_line(line)

        if not parsed:
            return

        client_ip, domain = parsed

        db = SessionLocal()
        try:
            db.add(DnsQuery(client_ip=client_ip, domain=domain))
            db.commit()

            # Cheap, no-extra-scheduler pruning — good enough for a log table
            # nobody needs perfectly bounded, just not unbounded.
            if random.random() < 0.01:
                cutoff = datetime.now(UTC) - timedelta(days=PRUNE_AFTER_DAYS)
                db.query(DnsQuery).filter(DnsQuery.queried_at < cutoff).delete()
                db.commit()
        except Exception:
            logger.exception("DnsSyslogProtocol: failed to persist DNS query from %s", addr[0])
            db.rollback()
        finally:
            db.close()


async def start_dns_listener() -> asyncio.DatagramTransport:
    loop = asyncio.get_event_loop()
    transport, _ = await loop.create_datagram_endpoint(
        DnsSyslogProtocol,
        local_addr=(settings.host, settings.dns_log_udp_port),
    )

    logger.info("DNS syslog listener bound to %s:%s/udp", settings.host, settings.dns_log_udp_port)

    return transport
