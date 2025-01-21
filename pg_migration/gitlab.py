import os
import time

import gitlab


class Gitlab:
    def __init__(self):
        url = 'https://' + os.environ['CI_SERVER_HOST']
        access_token = os.environ['ACCESS_TOKEN']
        self.gl = gitlab.Gitlab(url, access_token, api_version='4')
        self.gl.auth()

    def create_merge_request(self):
        project = self.gl.projects.get(os.environ['CI_PROJECT_ID'])
        branch = os.environ['CI_COMMIT_REF_NAME']
        message = f'auto-merge: {branch}'
        mr = project.mergerequests.create({
            'source_branch': branch,
            'target_branch': 'master',
            'title': message,
            'remove_source_branch': True
        })
        time.sleep(6)
        message = f"Merge branch '{branch}' into 'master'"
        if 'auto-deploy' in os.environ['CI_COMMIT_MESSAGE']:
            message = 'auto-deploy: ' + message
        mr.merge(
            merge_commit_message=message,
            merge_when_pipeline_succeeds=True
        )
