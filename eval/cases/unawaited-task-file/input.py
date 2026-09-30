import asyncio


async def charge(order, gateway, mailer):
    receipt = await gateway.charge(order.total)
    asyncio.create_task(mailer.send_receipt(order.email, receipt))
    return receipt
