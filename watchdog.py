#! /bin/python3.6

from pysnmp.hlapi import *
from datetime import datetime

import smtplib, imaplib, email
import re, urllib.request, serial
import time, os.path, subprocess

exchange_host = '192.168.0.1'
watchdog_mailbox = 'watchdog@domain.local'
mailbox_password = 'password'
warning_mailbox = 'admin@domain.local'

flags = '/home/user/watchdog/flags/'
logfile = '/home/user/watchdog/log.txt'
whitelist = '/home/user/watchdog/whitelist.txt'

modem = '/dev/ttyUSB2'

telegramToken = '000000aaaaaaaaaaahhhhhhhhhhhhhhhhhh'
telegramUrl = 'https://api.telegram.org/bot{}'.format(telegramToken)

smsToken = 'hhhhhhhhhh00000000000000aaaaaaaaaaaaaaaa'
smsUrl = 'http://ms.ru/sms/send?api_id={}&to='.format(smsToken)

denis = '79215555555'
kolya = '79815555555'
serg = '79625555555'

t_denis = '1234567890'


class Send:
    text = ''
    subject = 'Warning'
    numbers = [denis]
    tele_nums = [t_denis]


    # send message via telegram
    def telegram(self):
        nums = self.tele_nums
        text = self.text

        text = re.sub("^\s+|\n|\r|#|\s+$", '', text)
        text = text[0:250]

        for num in nums:
            url = '{}/sendmessage?chat_id={}&parse_mode=&text={}'.format(telegramUrl, num, text)
            log('Telegram API url: ' + url)
            try:
                urllib.request.urlopen(url)
                log('Telegram message "{}" sended'.format(text))
                return True
            except:
                log('Error send telegram message to {}'.format(num))
                return False


    # send sms via modem
    def sms(self):
        numbers = self.numbers
        text = self.text

        def sendAT(gsm, command, text):
            time.sleep(0.5)
            gsm.write(command)
            response = gsm.readall().decode()
            if("ERROR" in response):
                log('Error in AT-commands')
            log(response)


        try:
            gsm = serial.Serial(modem, 11520, timeout = 1)
            gsm.close()
            log('Open serial port')
            gsm.open()
            gsm.flushInput()
            gsm.flushOutput()

            for num in numbers:
                number = '+' + num

                log('Start send sms to {} with AT-commands'.format(number))

                sendAT(gsm, b'ATZ\r', text)
                sendAT(gsm, b'AT+CMGF=1\r', text)
                sendAT(gsm, b'AT+CMGS="' + number.encode() + b'"\r', text)
                sendAT(gsm, text.encode() + b'\r', text)
                sendAT(gsm, bytes([26]), text)

            log('Close serial port')
            gsm.close()
            return True

        except:
            log('Error send sms from modem to %s. Try to send SMS via Internet' % ', '.join(numbers))
            text = text.replace(' ', '_')
            phoneString = ','.join(numbers)
            try:
                # send sms via Internet
                urllib.request.urlopen(smsUrl + phoneString + '&msg=' + text + '&json=1')
                return True

            except:
                log('Error send SMS via internet to {}'.format(phoneString))
                return False

    # send message via exchange
    def mail(self):
        subject = self.subject
        text = self.text

        body = '\r\n'.join((
            'From: %s' % watchdog_mailbox,
            'To: %s' % warning_mailbox,
            'Subject: %s' % subject,
            '',
            text
        ))
        log('Try send mail to %s' % warning_mailbox)
        try:
            server = smtplib.SMTP(exchange_host)
            server.sendmail(watchdog_mailbox, [warning_mailbox], body)
            server.quit()
            return True
        except:
            log('Error send e-mail to %s' % warning_mailbox)
            return False


class SNMP:
    ip = ''
    port = '161'
    community = ''
    oid = ''
    status = ''
    name = ''
    error = False
    no_power = False

    def checkSnmp(self):
        errorIndication, errorStatus, errorIndex, varBinds = next(
            getCmd(SnmpEngine(),
                CommunityData(self.community, mpModel=0),
                UdpTransportTarget((self.ip, self.port)),
                ContextData(),
                ObjectType(ObjectIdentity(self.oid)))
        )

        if errorIndication:
            log(str(errorIndication))
            self.error = True
        elif errorStatus:
            log(str(errorStatus))
            self.error = True
        else:
            for name, val in varBinds:
                self.status = val



def log(text):
    text = text.replace('\n', ' ')
    print(text)
    file = open(logfile, 'a')
    file.write(getDate() + ': ' + text + '\n')
    file.close()


def getDate():
    now = datetime.strftime(datetime.now(), '%Y/%m/%d %H:%M:%S')
    return now


def check_flag(name):
    log('Start check flag {}'.format(name))
    file = flags + name
    if os.path.isfile(file):
        create_date = os.path.getctime(file)
        create_date = datetime.fromtimestamp(create_date)
        delta = datetime.now() - create_date
        log('Delta for flag {} {} days'.format(file, delta.days))
        if delta.days > 0:
            os.remove(file)
            log('remove flag "{}"'.format(file))
            return False
        else:
            log('Flag {} is active'.format(file))
            return True


def chk_whitelist(text):
    log('Start check whitelist')
    text = text.lower()
    with open(whitelist, 'r') as file:
        for line in file:
            line = (line.rstrip()).lower()
            if line in text:
                log('Match found')
                if not check_flag(line):
                    create_flag(line)
                    alarm = Send()
                    alarm.text = line
                    alarm.sms()
            else:
                print(line)
                print('AZAZA')
        pass
    log('No match')


def receiveMail():
    log('Start check e-mail')
    alarm = Send()

    mail = imaplib.IMAP4_SSL(exchange_host)
    mail.login(watchdog_mailbox, mailbox_password)
    mail.select('INBOX')

    status, data = mail.uid('search', None, 'ALL')

    for msg_id in data[0].split():
        status, data = mail.uid('fetch', msg_id, '(RFC822)')
        raw_email = data[0][1]
        msg = email.message_from_bytes(raw_email)

        if msg.is_multipart():
            for payload in msg.get_payload():
                if '<html' not in payload.get_payload():
                    alarm.text = payload.get_payload() # maybe lost data
        else:
            alarm.text = msg.get_payload()

        log('Received a new e-mail. Subject: {}.'.format(msg.get('subject')))

        chk_whitelist(alarm.text)

        alarm.telegram()


        mail.store(b'1', '+FLAGS', '\\Deleted')
        mail.expunge()

    mail.close()
    mail.logout()

def create_flag(name):
    log('Create flag {}'.format(name))
    file = flags + name
    with open(file, 'tw', encoding='utf-8') as f:
        pass


def check_symmetra():

    l_symmetra = SNMP()
    l_symmetra.ip = '192.168.0.2'
    l_symmetra.community = 'public'
    l_symmetra.oid = '1.3.6.1.4.1.318.1.1.1.2.1.2.0'
    l_symmetra.name = 'Left Symmetra'
    l_symmetra.checkSnmp()

    r_symmetra = SNMP()
    r_symmetra.ip = '192.168.0.3'
    r_symmetra.community = 'public'
    r_symmetra.oid = '1.3.6.1.4.1.318.1.1.1.2.1.2.0'
    r_symmetra.name = 'Right Symmetra'
    r_symmetra.checkSnmp()

    def chkPower(symm):
        log('Start chkPower {}'.format(symm.name))

        if not symm.error:
            if symm.status > -1:
                alarm = Send()
                alarm.text = '{} no power supply'.format(symm.name)
                log(alarm.text)
                if not check_flag(symm.name):
                    # alarm.sms()
                    alarm.telegram()
                    alarm.mail()
                symm.no_power = True
                create_flag(symm.name)
            else:
                symm.no_power = False
        else:
            alarm = Send()
            alarm.text = 'Error get snmp from {} '.format(symm.name)
            log(alarm.text)
            alarm.telegram()


    chkPower(l_symmetra)
    chkPower(r_symmetra)

    if l_symmetra.no_power and r_symmetra.no_power:
        log('All Symmetras no power')
        time.sleep(30)
        chkPower(l_symmetra)
        chkPower(r_symmetra)
        if l_symmetra.no_power and r_symmetra.no_power:
            log('Start pwershell script')
            proc = subprocess.Popen('pwsh /home/raist/watchdog/powershell.ps1', shell = True, stdout = subprocess.PIPE)
            out = proc.stdout.readlines()
            log('End powershell script')


send = Send()
send.text = 'Script started at %s' % getDate()
send.telegram()

while True:
    check_symmetra()
    receiveMail()
    time.sleep(20)
