#!/usr/bin/env python
#
# Copyright 2022 Google, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import json
import tempfile
import requests
from urllib import request, parse
from urllib.error import HTTPError
import logging

if __name__ == '__main__':

    logging.basicConfig(level=logging.INFO)

    # TODO grab random images from lorem picsum
    _, tmpname = tempfile.mkstemp(suffix='.jpg', dir='/tmp')

    request.urlretrieve("https://picsum.photos/1920/1080", tmpname)
    logging.info('Saved image to: %s', tmpname)

    basename = os.path.basename(tmpname)

    # call the task api to upload
    taskapi_url = '{}/uploadSignedUrl'.format(os.getenv('TASKAPI_URL'))
    data = json.dumps({'filename': basename})
    logging.info('calling task url {} with body {}'.format(taskapi_url, data))
    req = request.Request(taskapi_url, method="POST", data=data.encode('utf-8'))
    req.add_header('Content-Type', 'application/json')

    try:
        resp = request.urlopen(req)
        respbody = resp.read()
        encoding = resp.info().get_content_charset('utf8')  # JSON default
        respjson = json.loads(respbody.decode(encoding))
        logging.info("response: {}".format(respjson))

        logging.info('Uploading to GCS path: {} using url: {}'.format(respjson['gcsPath'], respjson['signedUrl']))

        # send the image to the signed URL
        signedUrl = respjson['signedUrl']
        mimeType = respjson['expectedContentType']
        headers = {"Content-Type": mimeType}
        with open(tmpname, mode='rb') as file: # b is important -> binary
            fileContent = file.read()
 
            uploadRes = requests.put(signedUrl, headers=headers, data=fileContent)
            logging.info('response={}'.format(uploadRes))
        
    except HTTPError as e:
        logging.error('error: {}'.format(e))
    finally:
        # TODO remove the file
        logging.info('Removing: %s', tmpname)
        os.remove(tmpname)

