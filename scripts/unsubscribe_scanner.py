#!/usr/bin/env python3
# Copyright (C) 2026 realvirtual GmbH
# This file is part of DeskAgent.
# AGPL-3.0-or-later - see LICENSE for details.


"""
Newsletter Unsubscribe Scanner
Durchsucht ToDelete Ordner nach Newslettern und extrahiert Unsubscribe-Links
"""

import re
import sys
from datetime import datetime
import pythoncom
import win32com.client


def get_outlook():
    """Initialisiert Outlook COM-Objekt"""
    pythoncom.CoInitialize()
    return win32com.client.Dispatch("Outlook.Application")


def find_todelete_folders(namespace):
    """Findet alle ToDelete Ordner in allen Mailboxen"""
    todelete_folders = []

    for store in namespace.Folders:
        mailbox_name = store.Name
        try:
            # Durchsuche alle Ordner in dieser Mailbox
            for folder in store.Folders:
                if folder.Name == "ToDelete":
                    todelete_folders.append({
                        'mailbox': mailbox_name,
                        'folder': folder
                    })
        except Exception as e:
            print(f"Fehler beim Durchsuchen von {mailbox_name}: {e}", file=sys.stderr)
            continue

    return todelete_folders


def extract_unsubscribe_links(body):
    """Extrahiert Unsubscribe-Links aus E-Mail-Body"""
    if not body:
        return []

    # Regex für URLs mit unsubscribe/abmelden/austragen
    patterns = [
        r'https?://[^\s<>"]+(?:unsubscribe|abmelden|austragen|opt-out|optout)[^\s<>"]*',
        r'<a[^>]+href=["\']([^"\']+(?:unsubscribe|abmelden|austragen|opt-out|optout)[^"\']*)["\']',
    ]

    links = []
    for pattern in patterns:
        matches = re.finditer(pattern, body, re.IGNORECASE)
        for match in matches:
            # Wenn es eine Gruppe gibt (href-Attribut), nehme die
            url = match.group(1) if len(match.groups()) > 0 else match.group(0)
            # Bereinige URL
            url = url.strip('<>"\' ')
            if url and url not in links:
                links.append(url)

    return links


def is_newsletter(subject, sender, body):
    """Prüft ob E-Mail ein Newsletter ist"""
    if not subject or not sender:
        return False

    # Newsletter-Indikatoren
    newsletter_keywords = [
        'newsletter', 'news', 'update', 'weekly', 'monthly', 'daily',
        'angebot', 'rabatt', 'sale', 'aktion', 'deal', 'discount',
        'marketing', 'promo', 'campaign', 'mailing'
    ]

    # Prüfe Betreff
    subject_lower = subject.lower()
    for keyword in newsletter_keywords:
        if keyword in subject_lower:
            return True

    # Prüfe ob Unsubscribe-Link vorhanden (starkes Indiz)
    if body:
        body_lower = body.lower()
        if 'unsubscribe' in body_lower or 'abmelden' in body_lower or 'austragen' in body_lower:
            return True

    # Prüfe Absender auf typische Newsletter-Absender
    sender_lower = sender.lower()
    if 'noreply' in sender_lower or 'newsletter' in sender_lower or 'marketing' in sender_lower:
        return True

    return False


def scan_todelete_folders():
    """Scannt alle ToDelete Ordner nach Newslettern"""
    outlook = get_outlook()
    namespace = outlook.GetNamespace("MAPI")

    print("Suche ToDelete Ordner...")
    todelete_folders = find_todelete_folders(namespace)

    print(f"Gefunden: {len(todelete_folders)} ToDelete Ordner")
    print()

    newsletters = []

    for folder_info in todelete_folders:
        mailbox = folder_info['mailbox']
        folder = folder_info['folder']

        print(f"Analysiere: {mailbox}/ToDelete")

        try:
            items = folder.Items
            items.Sort("[ReceivedTime]", True)  # Neueste zuerst

            count = 0
            for item in items:
                # Nur E-Mails (MailItem = 43)
                if item.Class != 43:
                    continue

                count += 1
                if count > 50:  # Limitiere auf 50 E-Mails pro Ordner
                    break

                try:
                    subject = item.Subject or ""
                    sender = item.SenderEmailAddress or ""
                    sender_name = item.SenderName or ""
                    received = item.ReceivedTime
                    body = item.Body or ""

                    # Prüfe ob Newsletter
                    if is_newsletter(subject, sender, body):
                        # Extrahiere Unsubscribe-Links
                        unsub_links = extract_unsubscribe_links(body)

                        newsletters.append({
                            'mailbox': mailbox,
                            'sender': sender,
                            'sender_name': sender_name,
                            'subject': subject,
                            'received': received,
                            'unsubscribe_links': unsub_links
                        })

                except Exception as e:
                    print(f"  Fehler bei E-Mail: {e}", file=sys.stderr)
                    continue

            print(f"  {count} E-Mails analysiert")

        except Exception as e:
            print(f"  Fehler beim Abrufen der E-Mails: {e}", file=sys.stderr)
            continue

    return newsletters


def print_results(newsletters):
    """Gibt die Ergebnisse formatiert aus"""
    print()
    print("=" * 150)
    print("NEWSLETTER ANALYSE - UNSUBSCRIBE MANAGEMENT")
    print("=" * 150)
    print()
    print(f"Gefunden: {len(newsletters)} Newsletter")
    print()

    if not newsletters:
        print("Keine Newsletter gefunden.")
        return

    # Gruppiere nach eindeutigen Absendern (Email-Adresse)
    unique_senders = {}
    for nl in newsletters:
        email = nl['sender']
        if email not in unique_senders:
            unique_senders[email] = nl

    print(f"Eindeutige Absender: {len(unique_senders)}")
    print()

    # Sortiere nach Absendername
    sorted_newsletters = sorted(unique_senders.values(), key=lambda x: x['sender_name'])

    # Detaillierte Ausgabe
    for idx, nl in enumerate(sorted_newsletters, 1):
        print(f"{idx}. {nl['sender_name']}")
        print(f"   E-Mail:     {nl['sender']}")
        print(f"   Mailbox:    {nl['mailbox']}")
        print(f"   Letzter Empfang: {nl['received'].strftime('%d.%m.%Y %H:%M')}")

        if nl['unsubscribe_links']:
            print(f"   Unsubscribe-Links:")
            for link in nl['unsubscribe_links']:
                print(f"      • {link}")
        else:
            print(f"   Unsubscribe-Link: NICHT GEFUNDEN")

        print()

    print("=" * 150)
    print()

    # Statistik
    with_links = sum(1 for nl in sorted_newsletters if nl['unsubscribe_links'])
    without_links = len(sorted_newsletters) - with_links

    print("STATISTIK:")
    print(f"  Newsletter mit Unsubscribe-Link:    {with_links} ({with_links*100//len(sorted_newsletters)}%)")
    print(f"  Newsletter ohne Unsubscribe-Link:   {without_links} ({without_links*100//len(sorted_newsletters)}%)")
    print()

    # CSV Export
    csv_filename = "E:\\aiassistant\\scripts\\newsletter_unsubscribe.csv"
    try:
        import csv
        with open(csv_filename, 'w', newline='', encoding='utf-8-sig') as csvfile:
            writer = csv.writer(csvfile, delimiter=';')
            writer.writerow(['Nr', 'Absender Name', 'E-Mail', 'Mailbox', 'Unsubscribe-Link', 'Anzahl Links'])

            for idx, nl in enumerate(sorted_newsletters, 1):
                links = ';'.join(nl['unsubscribe_links']) if nl['unsubscribe_links'] else 'NICHT GEFUNDEN'
                writer.writerow([
                    idx,
                    nl['sender_name'],
                    nl['sender'],
                    nl['mailbox'],
                    links,
                    len(nl['unsubscribe_links'])
                ])

        print(f"CSV Export erstellt: {csv_filename}")
        print()
    except Exception as e:
        print(f"CSV Export fehlgeschlagen: {e}")
        print()


if __name__ == "__main__":
    try:
        newsletters = scan_todelete_folders()
        print_results(newsletters)
    except Exception as e:
        print(f"FEHLER: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
