import boto3
import logging
import datetime
import os
from slugify import slugify
import sentry_sdk
from sentry_sdk.integrations.aws_lambda import AwsLambdaIntegration

sentry_sdk.init(dsn=os.environ.get('SENTRY_DSN'), integrations=[AwsLambdaIntegration()])

from ..utils.common_db_utils import chunks, BATCH_WRITE_CHUNK_SIZE
from common.utils.idea_utils import sanitize_idea_content, prepare_idea_tags_for_put_request, \
    prepare_idea_tags_for_delete_request, strip_html


# logger = logging.getLogger()
# logger.setLevel(logging.INFO)


def endpoint(event, lambda_context):
    ctx = event.get('ctx')
    arguments = ctx.get('arguments')
    title = arguments.get('title')
    slug = slugify(title)
    content = sanitize_idea_content(arguments.get('content', None))
    stripped_content = None
    if content:
        stripped_content = strip_html(content)

    idea_id = arguments.get('ideaId', None)
    idea_owner_id = arguments.get('ideaOwnerId', None)
    tags = arguments.get('tags', list())
    new_image_attachments = arguments.get('imageAttachments', list())
    new_file_attachments = arguments.get('fileAttachments', list())
    is_private = arguments.get('isPrivate', False)
    editor_id = ctx.get('identity').get('username')
    if editor_id != idea_owner_id:
        return {'result': {'ok': False, 'error': 'You do not have permission to edit this idea'}}
    if len(tags) > 100:
        return {'result': {'ok': False, 'error': 'Too much tags'}}
    client = boto3.client('dynamodb', region_name='us-east-1')
    s3 = boto3.client('s3')
    idea = client.get_item(
        TableName=os.environ.get('IDEAS_TABLE_NAME'),
        Key={
            'ideaId': {"S": idea_id},
            'userId': {"S": idea_owner_id}
        }
    )['Item']

    client.update_item(
        TableName=os.environ.get('IDEAS_TABLE_NAME'),
        Key={
            'ideaId': {"S": idea_id},
            'userId': {"S": idea_owner_id}
        },
        UpdateExpression='SET title = :title, slug = :slug, strippedContent = :strippedContent, content = :content, updatedDate = :updatedDate, fileAttachments=:fileAttachments, imageAttachments=:imageAttachments, previewImage=:previewImage, visibility=:visibility',
        ExpressionAttributeValues={
            ":title": {"S": title},
            ":slug": {"S": slug},
            ":strippedContent": {"S": stripped_content} if stripped_content else {"NULL": True},
            ":content": {"S": content} if content else {"NULL": True},
            ":updatedDate": {"S": datetime.datetime.now().isoformat()},
            ":fileAttachments": {"SS": new_file_attachments} if len(new_file_attachments) else {"NULL": True},
            ":imageAttachments": {"SS": new_image_attachments} if len(new_image_attachments) else {"NULL": True},
            ":previewImage": {"S": new_image_attachments[0]} if len(new_image_attachments) else {"NULL": True},
            ":visibility": {"S": "PRIVATE" if is_private else "PUBLIC"},
        }
    )
    current_file_attachments = idea['fileAttachments'].get('SS', [])
    for file_attachment in current_file_attachments:
        if file_attachment not in new_file_attachments:
            s3.delete_object(Bucket=os.environ.get('USER_UPLOADS_BUCKET'), Key=file_attachment)
    current_idea_tags = list(map(lambda t: t['tag']['S'], client.query(
        TableName=os.environ.get('TAGS_TABLE_NAME'),
        IndexName='ideaTags',
        ProjectionExpression='tag',
        KeyConditionExpression="ideaId = :ideaId",
        ExpressionAttributeValues={
            ":ideaId": {"S": idea_id}
        }
    )['Items']))
    if len(current_idea_tags):
        prepared_tags = prepare_idea_tags_for_delete_request(current_idea_tags, idea_id)
        for tags_chunk in chunks(prepared_tags, BATCH_WRITE_CHUNK_SIZE):
            client.batch_write_item(
                RequestItems={
                    os.environ.get('TAGS_TABLE_NAME'): tags_chunk
                }
            )
    if len(tags):
        prepared_tags = prepare_idea_tags_for_put_request(tags, idea_owner_id, idea_id)
        for tags_chunk in chunks(prepared_tags, BATCH_WRITE_CHUNK_SIZE):
            client.batch_write_item(
                RequestItems={
                    os.environ.get('TAGS_TABLE_NAME'): tags_chunk
                }
            )

    return {'result': {'ok': True}, 'idea': {'ideaId': idea_id, 'slug': slug}}
