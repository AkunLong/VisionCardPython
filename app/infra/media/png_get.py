import requests
from app.config import settings

async def img2png_2048x2048(image_in, image_path):
    img_in = image_in
    img_out = image_path
    response = requests.post(
        'https://api.pixian.ai/api/v2/remove-background',
        files={'image': open(f'{img_in}', 'rb')},
        data={
            # TODO: Add more upload options here
            # 'test':'true',
            'max_pixels': '4194304',
            'result.crop_to_foreground': 'True',
            'result.target_size': '2048 2048',
            'result.margin': '6.5%'
        },
        auth=(settings.PIXIAN_APP_ID, settings.PIXIAN_SECRET)
    )
    if response.status_code == requests.codes.ok:
        # Save result
        with open(f'{img_out}', 'wb') as out:
            out.write(response.content)
    else:
        print("Error:", response.status_code, response.text)

    return image_path